"""
Self-Organizing Perturbation Swarm Solver.

Implements a heterarchical swarm of agents that self-organize to solve
SWE-bench tasks through:
  1. Live communication via a shared ledger protocol
  2. Dynamic coordination with role planning and adaptation
  3. Test-driven verification and cross-agent endorsement
  4. Optional ChatOverflow integration for cross-run knowledge

Perturbation supports two modes:
  1. context_uncertainty: system-prompt uncertainty notices
  2. tool_io_degrade: hook-level degradations of verification tool outputs

Modes/intensity are controlled by HarnessConfig perturbation fields.

Architecture:
  Phase 0: PLANNING — single query() call plans 2-4 roles
  Phase 1: SWARM EXECUTION — N agents in parallel, shared workspace + ledger
  Phase 2: PATCH SELECTION — pick the most-verified fix from the ledger
"""

import asyncio
import json
import logging
import re
import subprocess
import tempfile
import time
from pathlib import Path

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    UserMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)

from ..config import HarnessConfig
from ..patch_hygiene import extract_changed_files, sanitize_patch
from ..perturbation_policy import PerturbationPolicy
from ..solver_agent import (
    CHATOVERFLOW_SWE_SKILL_PROMPT,
    _apply_task_specific_patch_remediation,
    ensure_sdk_stream_close_timeout,
    extract_patch,
    setup_workspace,
    streaming_user_prompt,
)
from ..task_selector import SWETask
from ..tracing import AgentTraceData, build_agent_hooks

logger = logging.getLogger(__name__)

_PASS_WORD_RE = re.compile(r"\b(pass|passed|success|resolved)\b", re.IGNORECASE)
_FAIL_WORD_RE = re.compile(r"\b(fail|failed|error|exception)\b", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SWARM_PROTOCOL_PROMPT = """
You are agent-{agent_num} in a self-organizing swarm of {num_agents} agents working together to solve a GitHub issue.

## Swarm Ledger Protocol

You share a workspace and a communication ledger with the other agents.
Use standard file tools to read/write ledger entries.

- Write your findings to: swarm_ledger/agent-{agent_num}/findings.md
- Read others' findings: check swarm_ledger/agent-*/findings.md
- Post your status: write "exploring" / "fixing" / "verifying" / "done" to swarm_ledger/agent-{agent_num}/status.md
- Post your hypothesis: swarm_ledger/agent-{agent_num}/hypothesis.md
- Propose a fix: write your diff to swarm_ledger/agent-{agent_num}/proposed_fix.diff (use `git diff --binary --no-ext-diff > swarm_ledger/agent-{agent_num}/proposed_fix.diff`)
- Verify others: apply their diff, run tests, write results to swarm_ledger/agent-{agent_num}/verification.md

## Coordination Rules

1. Check the ledger every ~5 tool calls to see what others have found
2. If someone else is already investigating a file you planned to look at, focus elsewhere or move to verification
3. Update your status.md when you transition between phases (exploring → fixing → verifying → done)
4. Before proposing a fix, run the relevant tests to validate it
5. If you see another agent's proposed_fix.diff, try to verify it by applying and running tests
6. Adapt your approach based on what the swarm is finding — do not duplicate work
7. Post important discoveries to findings.md so others can benefit

## Conflict Handling

If an edit fails because the file changed (another agent edited it), re-read the file
and check the ledger to understand what changed before retrying.

## Verification Reward

A proposed fix is only valid if you have run the relevant tests and they pass.
Post test results to the ledger. A fix endorsed by another agent (verified independently)
is the strongest signal of correctness.

## Your Suggested Focus

{role_goal}

This is a starting point. Adapt based on what you and others discover.

## Important Rules
- The repo is already cloned at the correct commit in your working directory
- Make changes directly -- do NOT create branches or commits
- Make **minimal, focused changes** -- only fix what the issue describes
- Do NOT add tests unless the issue specifically asks for them
- Do NOT modify test files unless the issue is about a test
- If maintainer discussion/hints are provided, follow maintainer consensus over reporter preference
{perturbation_text}{chatoverflow_prompt}
"""

PERTURBATION_PROMPTS = {
    0.0: "",
    0.05: (
        "\n## Uncertainty Notice\n"
        "Note: findings in the ledger may be incomplete. "
        "Cross-check before building on them.\n"
    ),
    0.10: (
        "\n## Uncertainty Notice\n"
        "Current hypotheses (yours and others') may be wrong. "
        "Verify each claim against the code before proceeding. "
        "Check at least one alternative explanation.\n"
    ),
    0.20: (
        "\n## Uncertainty Notice\n"
        "Findings from other agents and your own initial analysis are likely incomplete. "
        "Before acting on any hypothesis, actively seek disconfirming evidence. "
        "Do not trust unverified claims in the ledger.\n"
    ),
}

DEFAULT_ROLES = [
    {
        "name": "bug_reproducer",
        "goal": (
            "Find and run the relevant tests to reproduce the bug. "
            "Report exact error messages and failing test names."
        ),
    },
    {
        "name": "root_cause_tracer",
        "goal": (
            "Trace the error from the problem statement to the root cause in the source code. "
            "Identify the exact file and function."
        ),
    },
    {
        "name": "solution_architect",
        "goal": (
            "Understand the module architecture around the bug. "
            "Identify the minimal change needed and any edge cases."
        ),
    },
]

PLANNER_PROMPT = """Analyze this GitHub issue and decide what specialist roles a swarm of agents should take to solve it.

Consider the nature of the bug: is it a logic error, a missing feature, a race condition, a type error, etc.?
What different angles would help solve it faster?

Output 2-4 roles as a JSON array. Each role must have:
- "name": a short identifier (snake_case)
- "goal": one sentence describing the focus area

Output ONLY the JSON array, no other text.

Example output:
[
  {"name": "test_runner", "goal": "Find and run failing tests to reproduce the exact error."},
  {"name": "code_tracer", "goal": "Trace the error path through the source to find the root cause."},
  {"name": "fix_implementer", "goal": "Implement and verify a minimal fix once the root cause is identified."}
]
"""

# Maximum turns per swarm agent (lower than default since workload is shared)
SWARM_AGENT_MAX_TURNS = 50

# Maximum turns for the planner (lightweight, read-only)
PLANNER_MAX_TURNS = 5


# ---------------------------------------------------------------------------
# Phase 0: Plan roles
# ---------------------------------------------------------------------------


async def plan_roles(task: SWETask, repo_dir: Path, config: HarnessConfig) -> list[dict]:
    """
    Run a single lightweight planner agent to decide swarm roles.

    Uses query() with read-only tools and max_turns=5.
    On parse failure, returns DEFAULT_ROLES.
    """
    hints_section = ""
    if task.hints_text.strip():
        hints_section = (
            "\n### Maintainer Hints / Discussion\n\n"
            f"{task.hints_text.strip()}\n"
        )

    prompt = f"""{PLANNER_PROMPT}

## GitHub Issue

**Repository:** {task.repo}
**Instance ID:** {task.instance_id}

### Problem Statement

{task.problem_statement}
{hints_section}
"""

    options = ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": "You are a planner. Analyze the issue and output role assignments as JSON.",
        },
        model=config.model,
        permission_mode="bypassPermissions",
        cwd=str(repo_dir),
        allowed_tools=["Read", "Glob", "Grep", "Bash"],
        # Explicitly use project settings only (exclude user/local hooks).
        setting_sources=["project"],
        max_turns=PLANNER_MAX_TURNS,
    )

    last_text = ""
    try:
        async for message in query(
            prompt=streaming_user_prompt(prompt),
            options=options,
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        last_text = block.text
            elif isinstance(message, ResultMessage):
                logger.info(
                    f"[planner] Completed: turns={message.num_turns}, "
                    f"cost=${message.total_cost_usd or 0:.4f}"
                )
    except Exception as e:
        logger.warning(f"[planner] Failed: {e}, using default roles")
        return DEFAULT_ROLES

    # Parse JSON from the last assistant text
    roles = _parse_roles_json(last_text)
    if roles:
        logger.info(f"[planner] Planned {len(roles)} roles: {[r['name'] for r in roles]}")
        return roles

    logger.warning("[planner] Could not parse roles, using defaults")
    return DEFAULT_ROLES


def _parse_roles_json(text: str) -> list[dict] | None:
    """Extract and validate a JSON roles array from text."""
    # Try to find JSON array in the text
    # Look for [...] pattern
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if not match:
        return None

    try:
        roles = json.loads(match.group())
    except json.JSONDecodeError:
        return None

    # Validate structure
    if not isinstance(roles, list) or len(roles) < 2 or len(roles) > 4:
        return None

    for role in roles:
        if not isinstance(role, dict):
            return None
        if "name" not in role or "goal" not in role:
            return None
        if not isinstance(role["name"], str) or not isinstance(role["goal"], str):
            return None

    return roles


# ---------------------------------------------------------------------------
# Phase 1: Swarm execution
# ---------------------------------------------------------------------------


async def run_swarm_agent(
    agent_num: int,
    role: dict,
    task: SWETask,
    repo_dir: Path,
    ledger_dir: Path,
    num_agents: int,
    config: HarnessConfig,
    intensity: float,
    perturbation_policy: PerturbationPolicy,
    trace_data: AgentTraceData,
    agent_api_key: str,
) -> None:
    """
    Run a single swarm agent with the shared workspace and ledger.

    The agent gets:
    - A role suggestion (starting point, not rigid)
    - Access to the shared repo directory
    - Read/write access to the swarm ledger
    - Perturbation text injected into system prompt
    - Optional ChatOverflow access
    """
    # Context perturbation text only applies in context_uncertainty mode.
    perturbation_text = _get_context_perturbation_text(
        config.perturbation_mode,
        intensity,
    )

    # Build ChatOverflow prompt if enabled
    chatoverflow_prompt = ""
    if config.enable_chatoverflow:
        chatoverflow_prompt = "\n" + CHATOVERFLOW_SWE_SKILL_PROMPT.format(
            chatoverflow_api_url=config.chatoverflow_api_url,
        )

    # Build the system prompt
    system_prompt = SWARM_PROTOCOL_PROMPT.format(
        agent_num=agent_num,
        num_agents=num_agents,
        role_goal=role["goal"],
        perturbation_text=perturbation_text,
        chatoverflow_prompt=chatoverflow_prompt,
    )

    # Build environment variables
    env = {}
    if config.enable_chatoverflow and agent_api_key:
        env["CHATOVERFLOW_API_URL"] = config.chatoverflow_api_url
        env["CHATOVERFLOW_API_KEY"] = agent_api_key

    hooks = build_agent_hooks(
        trace_data,
        perturbation_policy=perturbation_policy,
        phase_tag="swarm_phase1",
    )

    options = ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": system_prompt,
        },
        model=config.model,
        permission_mode="bypassPermissions",
        cwd=str(repo_dir),
        allowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep"],
        # Explicitly use project settings only (exclude user/local hooks).
        setting_sources=["project"],
        env=env,
        max_turns=SWARM_AGENT_MAX_TURNS,
        hooks=hooks,
    )

    hints_section = ""
    if task.hints_text.strip():
        hints_section = (
            "\n### Maintainer Hints / Discussion\n\n"
            f"{task.hints_text.strip()}\n"
        )

    prompt = f"""## GitHub Issue to Solve

**Repository:** {task.repo}
**Instance ID:** {task.instance_id}

### Problem Statement

{task.problem_statement}
{hints_section}

---

The repository is already cloned in your working directory and checked out at commit `{task.base_commit}`.

You are agent-{agent_num} (role: {role['name']}). Your initial focus: {role['goal']}

The swarm ledger is at `swarm_ledger/` in the repo directory. Your ledger directory is `swarm_ledger/agent-{agent_num}/`.
Check other agents' ledger directories periodically to coordinate.

Explore the repository, understand the code, coordinate with other agents via the ledger, and fix the issue.
Make minimal changes, do not create branches or commits, just edit the files directly.
"""

    agent_label = f"swarm-agent-{agent_num}"
    trace_data.prompt = prompt

    logger.info(
        f"[{agent_label}] Starting (role: {role['name']}, "
        f"mode: {config.perturbation_mode}, intensity: {intensity})"
    )
    ensure_sdk_stream_close_timeout()

    try:
        async for message in query(
            prompt=streaming_user_prompt(prompt),
            options=options,
        ):
            if isinstance(message, AssistantMessage):
                content_dicts = []
                for block in message.content:
                    if isinstance(block, TextBlock):
                        content_dicts.append({"type": "text", "text": block.text})
                        if len(block.text) > 100:
                            logger.debug(f"[{agent_label}] text: {block.text[:100]}...")
                    elif isinstance(block, ToolUseBlock):
                        content_dicts.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })
                        logger.info(f"[{agent_label}] tool: {block.name}")

                trace_data.messages.append({
                    "type": "assistant",
                    "model": message.model,
                    "content": content_dicts,
                })

            elif isinstance(message, UserMessage):
                if isinstance(message.content, list):
                    for block in message.content:
                        if isinstance(block, ToolResultBlock):
                            trace_data.messages.append({
                                "type": "tool_result",
                                "tool_use_id": block.tool_use_id,
                                "content": str(block.content)[:2000] if block.content else "",
                                "is_error": block.is_error or False,
                            })

            elif isinstance(message, ResultMessage):
                trace_data.num_turns = message.num_turns
                trace_data.total_cost_usd = message.total_cost_usd or 0.0
                logger.info(
                    f"[{agent_label}] Completed: turns={message.num_turns}, "
                    f"cost=${message.total_cost_usd or 0:.4f}, "
                    f"error={message.is_error}"
                )
                if message.is_error:
                    trace_data.error = f"agent_error: {message.result}"

    except Exception as e:
        logger.error(f"[{agent_label}] Failed: {e}")
        trace_data.error = f"agent_exception: {e}"

    _ensure_agent_proposed_diff(
        repo_dir=repo_dir,
        ledger_dir=ledger_dir,
        agent_num=agent_num,
    )


def _get_context_perturbation_text(mode: str, intensity: float) -> str:
    """Get uncertainty prompt text when running context perturbation mode."""
    if mode != "context_uncertainty":
        return ""
    if intensity <= 0.0:
        return ""
    # Find the closest defined level at or below the given intensity
    levels = sorted(PERTURBATION_PROMPTS.keys())
    selected = 0.0
    for level in levels:
        if level <= intensity:
            selected = level
    return PERTURBATION_PROMPTS.get(selected, "")


def _ensure_agent_proposed_diff(repo_dir: Path, ledger_dir: Path, agent_num: int) -> None:
    """
    Ensure each agent ends with a sanitized proposed diff in the ledger.

    If the agent wrote a diff, sanitize it in-place.
    If not, snapshot current workspace diff as a fallback proposal.
    """
    diff_file = ledger_dir / f"agent-{agent_num}" / "proposed_fix.diff"
    existing = diff_file.read_text(errors="replace") if diff_file.exists() else ""

    sanitized_existing = sanitize_patch(existing, fail_closed_on_special=True)
    if existing.strip() and not sanitized_existing.rejected and sanitized_existing.patch.strip():
        if sanitized_existing.patch != existing:
            diff_file.write_text(sanitized_existing.patch)
        return

    snapshot = extract_patch(repo_dir)
    if snapshot.strip():
        diff_file.write_text(snapshot)


# ---------------------------------------------------------------------------
# Phase 2: Patch selection
# ---------------------------------------------------------------------------


def select_best_patch(repo_dir: Path, ledger_dir: Path, num_agents: int) -> str:
    """
    Select the best patch from the swarm's work.

    Priority:
    1. A fix verified by another agent (endorsed) — apply that agent's diff
    2. Multiple fixes — pick the one with strongest verification signal
    3. If no candidate applies, use the sanitized workspace snapshot

    Returns the patch string.
    """
    # Keep a pre-selection snapshot as the final fallback.
    workspace_snapshot = extract_patch(repo_dir)

    # Score each agent's proposal by verification notes.
    verification_scores: dict[int, int] = {i: 0 for i in range(num_agents)}

    for agent_i in range(num_agents):
        verification_file = ledger_dir / f"agent-{agent_i}" / "verification.md"
        if not verification_file.exists():
            continue
        content = verification_file.read_text(errors="replace")
        for agent_j in range(num_agents):
            if agent_j == agent_i:
                continue
            verification_scores[agent_j] += _score_verification_for_agent(
                content,
                agent_j,
            )

    # Load/sanitize candidate diffs before touching the workspace.
    candidates: list[dict] = []
    for agent_i in range(num_agents):
        diff_file = ledger_dir / f"agent-{agent_i}" / "proposed_fix.diff"
        if diff_file.exists():
            raw_patch = diff_file.read_text(errors="replace")
            sanitized = sanitize_patch(raw_patch, fail_closed_on_special=True)
            if sanitized.rejected:
                logger.warning(
                    "[patch-select] Rejecting agent-%d proposed diff (%s)",
                    agent_i,
                    sanitized.reason,
                )
                continue
            if not sanitized.patch.strip():
                continue
            candidates.append(
                {
                    "agent": agent_i,
                    "score": verification_scores.get(agent_i, 0),
                    "patch": sanitized.patch,
                    "allowed_files": set(sanitized.kept_files)
                    or extract_changed_files(sanitized.patch),
                }
            )

    if not candidates:
        if workspace_snapshot.strip():
            logger.warning(
                "[patch-select] No valid proposed diffs; using sanitized workspace snapshot",
            )
        return workspace_snapshot

    candidates.sort(
        key=lambda item: (item["score"], len(item["patch"])),
        reverse=True,
    )

    for candidate in candidates:
        applied_patch = _apply_candidate_patch(
            repo_dir=repo_dir,
            agent_num=int(candidate["agent"]),
            candidate_patch=str(candidate["patch"]),
            allowed_files=set(candidate["allowed_files"]),
        )
        if applied_patch.strip():
            return applied_patch

    if workspace_snapshot.strip():
        logger.warning(
            "[patch-select] Candidate apply failed; using sanitized workspace snapshot",
        )
    return workspace_snapshot


def _score_verification_for_agent(verification_text: str, agent_num: int) -> int:
    score = 0
    for line in verification_text.splitlines():
        lowered = line.lower()
        if f"agent-{agent_num}" not in lowered:
            continue
        if _PASS_WORD_RE.search(line):
            score += 1
        if _FAIL_WORD_RE.search(line):
            score -= 1
    return score


def _restore_workspace_for_patch_apply(repo_dir: Path) -> bool:
    checkout = subprocess.run(
        ["git", "checkout", "--", "."],
        cwd=str(repo_dir),
        capture_output=True,
        timeout=30,
    )
    clean = subprocess.run(
        ["git", "clean", "-fd"],
        cwd=str(repo_dir),
        capture_output=True,
        timeout=30,
    )
    return checkout.returncode == 0 and clean.returncode == 0


def _apply_candidate_patch(
    *,
    repo_dir: Path,
    agent_num: int,
    candidate_patch: str,
    allowed_files: set[str],
) -> str:
    if not _restore_workspace_for_patch_apply(repo_dir):
        logger.warning("[patch-select] Failed to restore workspace before patch apply")
        return ""

    try:
        with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=True) as tmp:
            tmp.write(candidate_patch)
            tmp.flush()

            check = subprocess.run(
                ["git", "apply", "--check", "--allow-empty", tmp.name],
                cwd=str(repo_dir),
                capture_output=True,
                timeout=30,
            )
            if check.returncode != 0:
                logger.warning(
                    "[patch-select] Agent-%d diff failed --check: %s",
                    agent_num,
                    check.stderr.decode(errors="replace")[:200],
                )
                return ""

            apply_result = subprocess.run(
                ["git", "apply", "--allow-empty", tmp.name],
                cwd=str(repo_dir),
                capture_output=True,
                timeout=30,
            )
            if apply_result.returncode != 0:
                logger.warning(
                    "[patch-select] Agent-%d diff apply failed: %s",
                    agent_num,
                    apply_result.stderr.decode(errors="replace")[:200],
                )
                return ""
    except Exception as exc:
        logger.warning(
            "[patch-select] Error applying agent-%d candidate: %s",
            agent_num,
            exc,
        )
        return ""

    patch = extract_patch(
        repo_dir,
        allowed_files=allowed_files if allowed_files else None,
    )
    if patch.strip():
        logger.info(
            "[patch-select] Selected agent-%d patch (%d bytes)",
            agent_num,
            len(patch),
        )
    return patch


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def solve_swe_task(
    task: SWETask,
    agent_id: str,
    workspace_dir: Path,
    ref_repo_dir: Path,
    config: HarnessConfig,
    trace_data: AgentTraceData,
    agent_api_key: str = "",
) -> dict:
    """
    Run the perturbation swarm solver on a SWE-bench task.

    This is the entry point called by the harness. It orchestrates:
      Phase 0: Plan roles (single lightweight agent)
      Phase 1: Launch swarm agents in parallel (shared workspace + ledger)
      Phase 2: Select the best patch from ledger entries

    Args:
        task: The SWE-bench task to solve
        agent_id: Unique agent identifier (from harness)
        workspace_dir: Isolated workspace directory for this task
        ref_repo_dir: Pre-cloned reference repo to copy from
        config: Harness configuration
        trace_data: Tracing data accumulator
        agent_api_key: Optional ChatOverflow API key

    Returns:
        Dict with instance_id, model_patch, model_name_or_path, and metadata
    """
    start_time = time.time()
    intensity = config.perturbation_intensity
    mode = config.perturbation_mode

    logger.info(
        f"[{agent_id}] Perturbation swarm solver starting "
        f"(mode={mode}, intensity={intensity}, seed={config.perturbation_seed})"
    )

    # Setup workspace by copying from reference repo
    try:
        repo_dir = await asyncio.to_thread(
            setup_workspace, task, workspace_dir, ref_repo_dir
        )
    except Exception as e:
        logger.error(f"[{agent_id}] Failed to setup workspace: {e}")
        trace_data.error = f"workspace_setup: {e}"
        return {
            "instance_id": task.instance_id,
            "model_name_or_path": f"kekule-swarm-{config.model}",
            "model_patch": "",
            "agent_id": agent_id,
            "error": str(e),
        }

    ledger_dir = repo_dir / "swarm_ledger"
    swarm_policy = PerturbationPolicy(
        mode=mode,
        intensity=intensity,
        target_tools=tuple(config.perturbation_target_tools),
        seed=config.perturbation_seed,
        phase_scope=config.perturbation_phase_scope,
    )

    # ------------------------------------------------------------------
    # Phase 0: Plan roles
    # ------------------------------------------------------------------
    logger.info(f"[{agent_id}] Phase 0: Planning roles...")
    roles = await plan_roles(task, repo_dir, config)
    logger.info(
        f"[{agent_id}] Phase 0: Planned {len(roles)} roles: "
        f"{[r['name'] for r in roles]}"
    )

    # Initialize ledger directories
    for i in range(len(roles)):
        agent_ledger = ledger_dir / f"agent-{i}"
        agent_ledger.mkdir(parents=True, exist_ok=True)
        (agent_ledger / "status.md").write_text("exploring")
        (agent_ledger / "findings.md").write_text(
            f"# Agent-{i} Findings ({roles[i]['name']})\n\n"
        )

    # ------------------------------------------------------------------
    # Phase 1: Swarm execution (all agents in parallel, shared workspace)
    # ------------------------------------------------------------------
    logger.info(
        f"[{agent_id}] Phase 1: Launching {len(roles)} swarm agents in parallel..."
    )

    # Create per-agent trace data (accumulate cost/turns into the parent)
    agent_trace_datas = []
    for i, role in enumerate(roles):
        atd = AgentTraceData(
            agent_id=f"{agent_id}-swarm-{i}",
            instance_id=task.instance_id,
            agent_num=i,
            iteration=trace_data.iteration,
            model=config.model,
        )
        agent_trace_datas.append(atd)

    await asyncio.gather(*[
        run_swarm_agent(
            agent_num=i,
            role=role,
            task=task,
            repo_dir=repo_dir,
            ledger_dir=ledger_dir,
            num_agents=len(roles),
            config=config,
            intensity=intensity,
            perturbation_policy=swarm_policy,
            trace_data=agent_trace_datas[i],
            agent_api_key=agent_api_key,
        )
        for i, role in enumerate(roles)
    ])

    # Aggregate trace data from all swarm agents
    total_turns = 0
    total_cost = 0.0
    all_messages = []
    all_perturbation_events = []
    total_perturbation_eligible = 0
    total_perturbation_fired = 0
    errors = []
    for atd in agent_trace_datas:
        total_turns += atd.num_turns
        total_cost += atd.total_cost_usd
        all_messages.extend(atd.messages)
        all_perturbation_events.extend(atd.perturbation_events)
        total_perturbation_eligible += atd.perturbation_eligible
        total_perturbation_fired += atd.perturbation_fired
        if atd.error:
            errors.append(atd.error)

    trace_data.num_turns = total_turns
    trace_data.total_cost_usd = total_cost
    trace_data.messages = all_messages
    trace_data.perturbation_policy_id = swarm_policy.policy_id
    trace_data.perturbation_events = all_perturbation_events
    trace_data.perturbation_eligible = total_perturbation_eligible
    trace_data.perturbation_fired = total_perturbation_fired
    if errors:
        trace_data.error = "; ".join(errors)

    # ------------------------------------------------------------------
    # Phase 2: Select best patch
    # ------------------------------------------------------------------
    logger.info(f"[{agent_id}] Phase 2: Selecting best patch...")
    patch = select_best_patch(repo_dir, ledger_dir, len(roles))
    patch = _apply_task_specific_patch_remediation(task, repo_dir, patch)
    trace_data.patch_produced = bool(patch.strip())
    trace_data.patch_content = patch

    elapsed = time.time() - start_time
    logger.info(
        f"[{agent_id}] Finished in {elapsed:.1f}s, "
        f"patch={'yes' if patch.strip() else 'no'} "
        f"({len(patch)} bytes), "
        f"total_turns={total_turns}, total_cost=${total_cost:.4f}, "
        f"perturbation_fired={total_perturbation_fired}/{total_perturbation_eligible}"
    )

    return {
        "instance_id": task.instance_id,
        "model_name_or_path": f"kekule-swarm-{config.model}",
        "model_patch": patch,
        "agent_id": agent_id,
        "duration_s": elapsed,
        "num_turns": total_turns,
        "cost_usd": total_cost,
        "swarm_agents": len(roles),
        "perturbation_mode": mode,
        "perturbation_policy_id": swarm_policy.policy_id,
        "perturbation_intensity": intensity,
        "perturbation_eligible": total_perturbation_eligible,
        "perturbation_fired": total_perturbation_fired,
        "perturbation_fire_rate": (
            total_perturbation_fired / total_perturbation_eligible
            if total_perturbation_eligible > 0
            else 0.0
        ),
        "roles": [r["name"] for r in roles],
    }


__all__ = ["solve_swe_task"]
