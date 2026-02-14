"""
Tool I/O Perturbation Swarm Solver (Experiment v0.2).

Fork of perturbation_swarm.py that replaces context perturbation with
tool I/O perturbation via PostToolUse hooks on Bash output.

Instead of injecting uncertainty text into agent system prompts,
this solver intercepts test command output and degrades it:
  - Truncates output to fewer lines
  - Redacts file paths in error messages
  - Replaces error names with generic [ERROR] tokens

The perturbation targets the verification mechanism itself, testing
whether agents can fall back to code-level reasoning when test signals
are weak.

Architecture (same 3-phase as v0.1):
  Phase 0: PLANNING — single query() call plans 2-4 roles (unperturbed)
  Phase 1: SWARM EXECUTION — N agents in parallel, tool I/O perturbed
  Phase 2: PATCH SELECTION — pick the most-verified fix (unperturbed)
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
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
    HookMatcher,
)
from claude_agent_sdk.types import PostToolUseHookInput, HookContext

from ..config import HarnessConfig
from ..solver_agent import (
    CHATOVERFLOW_SWE_SKILL_PROMPT,
    extract_patch,
    setup_workspace,
)
from ..task_selector import SWETask
from ..tracing import AgentTraceData, build_agent_hooks

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Test command detection
# ---------------------------------------------------------------------------

TEST_PATTERNS = [
    re.compile(r"\bpytest\b"),
    re.compile(r"\bpython\s+-m\s+pytest\b"),
    re.compile(r"manage\.py\s+test"),
    re.compile(r"\btox\b"),
    re.compile(r"\bpython\s+-m\s+unittest\b"),
    re.compile(r"\bpython\s+.*test.*\.py\b"),
    re.compile(r"\./runtests\.py\b"),
    re.compile(r"python\s+tests/runtests\.py"),
]

# Commands that mention test tools but are NOT test invocations
_INSTALL_RE = re.compile(r"\b(?:pip|uv|conda)\s+install\b")


def is_test_command(command: str) -> bool:
    """Check if a Bash command is a test invocation."""
    if _INSTALL_RE.search(command):
        return False
    return any(p.search(command) for p in TEST_PATTERNS)


# ---------------------------------------------------------------------------
# Output degradation functions
# ---------------------------------------------------------------------------

# Matches typical Python file paths in tracebacks and error messages
_FILE_PATH_RE = re.compile(
    r'(?:File\s+")([^"]+\.py)"'  # File "path/to/file.py"
    r"|"
    r"(/[^\s:]+\.py(?::\d+)?)"  # /absolute/path.py:123
    r"|"
    r"([\w./\\]+\.py(?::\d+)?)"  # relative/path.py:123
)

# Matches common Python exception class names
_ERROR_NAME_RE = re.compile(r"\b([A-Z][a-zA-Z]*(?:Error|Exception|Warning|Failure))\b")


def truncate_test_output(output: str, intensity: float) -> str:
    """
    Degrade test output based on intensity level.

    Intensity ladder:
      0.00 — no modification (baseline)
      0.05 — truncate to last 30 lines
      0.10 — truncate to last 15 lines + redact file paths
      0.20 — truncate to last 5 lines + redact paths + replace error names
    """
    if intensity <= 0.0:
        return output

    lines = output.splitlines()

    if intensity <= 0.05:
        # Low: keep last 30 lines
        tail = lines[-30:] if len(lines) > 30 else lines
        return "\n".join(tail)

    if intensity <= 0.10:
        # Medium: keep last 15 lines + redact file paths
        tail = lines[-15:] if len(lines) > 15 else lines
        result = "\n".join(tail)
        result = _redact_file_paths(result)
        return result

    # High (0.20+): keep last 5 lines + redact paths + replace error names
    tail = lines[-5:] if len(lines) > 5 else lines
    result = "\n".join(tail)
    result = _redact_file_paths(result)
    result = _redact_error_names(result)
    return result


def _redact_file_paths(text: str) -> str:
    """Replace file paths with [REDACTED_PATH]."""

    def _replace(m: re.Match) -> str:
        if m.group(1):
            return 'File "[REDACTED_PATH]"'
        return "[REDACTED_PATH]"

    return _FILE_PATH_RE.sub(_replace, text)


def _redact_error_names(text: str) -> str:
    """Replace Python exception class names with [ERROR]."""
    return _ERROR_NAME_RE.sub("[ERROR]", text)


def _count_redactions(original: str, modified: str) -> list[str]:
    """Identify which redaction types were applied."""
    applied = []
    if "[REDACTED_PATH]" in modified and "[REDACTED_PATH]" not in original:
        applied.append("file_paths")
    if "[ERROR]" in modified and "[ERROR]" not in original:
        applied.append("error_names")
    return applied


# ---------------------------------------------------------------------------
# Perturbation hooks
# ---------------------------------------------------------------------------


def build_perturbation_hooks(
    intensity: float,
    agent_label: str,
    instance_id: str,
    perturbation_log: list[dict],
) -> list:
    """
    Build PostToolUse HookMatcher(s) that degrade Bash test output.

    Returns a list of HookMatcher instances to be composed with
    tracing hooks via build_agent_hooks(extra_post_hooks=...).
    """
    if intensity <= 0.0:
        return []

    async def perturb_tool_output(
        input_data: PostToolUseHookInput,
        tool_use_id: str | None,
        context: HookContext,
    ):
        try:
            tool_name = input_data.get("tool_name", "")
            if tool_name != "Bash":
                return {}

            tool_input = input_data.get("tool_input", {})
            command = (
                tool_input.get("command", "")
                if isinstance(tool_input, dict)
                else str(tool_input)
            )

            if not is_test_command(command):
                return {}

            tool_output = input_data.get("tool_response", "")
            if not isinstance(tool_output, str):
                tool_output = str(tool_output)

            original_lines = len(tool_output.splitlines())
            truncated = truncate_test_output(tool_output, intensity)
            truncated_lines = len(truncated.splitlines())
            redactions = _count_redactions(tool_output, truncated)

            # Log the perturbation event
            perturbation_log.append(
                {
                    "ts": time.time(),
                    "agent_id": agent_label,
                    "task_id": instance_id,
                    "event": "PostToolUse",
                    "tool_name": "Bash",
                    "command_hash": hashlib.sha256(command.encode()).hexdigest()[:16],
                    "is_test_command": True,
                    "perturbation_fired": True,
                    "intensity": intensity,
                    "original_output_lines": original_lines,
                    "truncated_output_lines": truncated_lines,
                    "redactions_applied": redactions,
                }
            )

            logger.info(
                f"[{agent_label}] Perturbation fired: "
                f"{original_lines} → {truncated_lines} lines, "
                f"redactions={redactions}"
            )

            # Replace the tool output with the degraded version
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "updatedMCPToolOutput": truncated,
                },
            }

        except Exception as e:
            # Never let perturbation hooks crash the agent
            logger.warning(f"[{agent_label}] Perturbation hook error: {e}")
            return {}

    return [HookMatcher(hooks=[perturb_tool_output])]


# ---------------------------------------------------------------------------
# Prompts (same swarm protocol as v0.1, but NO context perturbation text)
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
- Propose a fix: write your diff to swarm_ledger/agent-{agent_num}/proposed_fix.diff (use `git diff > swarm_ledger/agent-{agent_num}/proposed_fix.diff`)
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
{chatoverflow_prompt}
"""

# Maximum turns per swarm agent
SWARM_AGENT_MAX_TURNS = 50

# Maximum turns for the planner
PLANNER_MAX_TURNS = 5

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


# ---------------------------------------------------------------------------
# Phase 0: Plan roles (identical to perturbation_swarm.py — unperturbed)
# ---------------------------------------------------------------------------


async def plan_roles(
    task: SWETask, repo_dir: Path, config: HarnessConfig
) -> list[dict]:
    """Run a single lightweight planner agent to decide swarm roles."""
    prompt = f"""{PLANNER_PROMPT}

## GitHub Issue

**Repository:** {task.repo}
**Instance ID:** {task.instance_id}

### Problem Statement

{task.problem_statement}
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
        setting_sources=[],
        max_turns=PLANNER_MAX_TURNS,
    )

    last_text = ""
    try:
        async for message in query(prompt=prompt, options=options):
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

    roles = _parse_roles_json(last_text)
    if roles:
        logger.info(
            f"[planner] Planned {len(roles)} roles: {[r['name'] for r in roles]}"
        )
        return roles

    logger.warning("[planner] Could not parse roles, using defaults")
    return DEFAULT_ROLES


def _parse_roles_json(text: str) -> list[dict] | None:
    """Extract and validate a JSON roles array from text."""
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return None

    try:
        roles = json.loads(match.group())
    except json.JSONDecodeError:
        return None

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
# Phase 1: Swarm execution (with tool I/O perturbation hooks)
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
    trace_data: AgentTraceData,
    agent_api_key: str,
    perturbation_log: list[dict],
) -> None:
    """
    Run a single swarm agent with tool I/O perturbation hooks.

    Unlike perturbation_swarm.py, this does NOT inject uncertainty text
    into the system prompt.  Instead, it attaches PostToolUse hooks that
    intercept and degrade Bash test output at the configured intensity.
    """
    agent_label = f"swarm-agent-{agent_num}"

    # Build ChatOverflow prompt if enabled
    chatoverflow_prompt = ""
    if config.enable_chatoverflow:
        chatoverflow_prompt = "\n" + CHATOVERFLOW_SWE_SKILL_PROMPT.format(
            chatoverflow_api_url=config.chatoverflow_api_url,
        )

    system_prompt = SWARM_PROTOCOL_PROMPT.format(
        agent_num=agent_num,
        num_agents=num_agents,
        role_goal=role["goal"],
        chatoverflow_prompt=chatoverflow_prompt,
    )

    # Build environment variables
    env = {}
    if config.enable_chatoverflow and agent_api_key:
        env["CHATOVERFLOW_API_URL"] = config.chatoverflow_api_url
        env["CHATOVERFLOW_API_KEY"] = agent_api_key

    # Build perturbation hooks (empty list at intensity 0.0)
    extra_hooks = build_perturbation_hooks(
        intensity=intensity,
        agent_label=agent_label,
        instance_id=task.instance_id,
        perturbation_log=perturbation_log,
    )

    # Compose tracing + perturbation hooks
    hooks = build_agent_hooks(trace_data, extra_post_hooks=extra_hooks)

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
        setting_sources=["user"],
        env=env,
        max_turns=SWARM_AGENT_MAX_TURNS,
        hooks=hooks,
    )

    prompt = f"""## GitHub Issue to Solve

**Repository:** {task.repo}
**Instance ID:** {task.instance_id}

### Problem Statement

{task.problem_statement}

---

The repository is already cloned in your working directory and checked out at commit `{task.base_commit}`.

You are agent-{agent_num} (role: {role["name"]}). Your initial focus: {role["goal"]}

The swarm ledger is at `swarm_ledger/` in the repo directory. Your ledger directory is `swarm_ledger/agent-{agent_num}/`.
Check other agents' ledger directories periodically to coordinate.

Explore the repository, understand the code, coordinate with other agents via the ledger, and fix the issue.
Make minimal changes, do not create branches or commits, just edit the files directly.
"""

    trace_data.prompt = prompt
    logger.info(
        f"[{agent_label}] Starting (role: {role['name']}, intensity: {intensity})"
    )

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                content_dicts = []
                for block in message.content:
                    if isinstance(block, TextBlock):
                        content_dicts.append({"type": "text", "text": block.text})
                        if len(block.text) > 100:
                            logger.debug(f"[{agent_label}] text: {block.text[:100]}...")
                    elif isinstance(block, ToolUseBlock):
                        content_dicts.append(
                            {
                                "type": "tool_use",
                                "id": block.id,
                                "name": block.name,
                                "input": block.input,
                            }
                        )
                        logger.info(f"[{agent_label}] tool: {block.name}")

                trace_data.messages.append(
                    {
                        "type": "assistant",
                        "model": message.model,
                        "content": content_dicts,
                    }
                )

            elif isinstance(message, UserMessage):
                if isinstance(message.content, list):
                    for block in message.content:
                        if isinstance(block, ToolResultBlock):
                            trace_data.messages.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": block.tool_use_id,
                                    "content": str(block.content)[:2000]
                                    if block.content
                                    else "",
                                    "is_error": block.is_error or False,
                                }
                            )

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


# ---------------------------------------------------------------------------
# Phase 2: Patch selection (identical to perturbation_swarm.py — unperturbed)
# ---------------------------------------------------------------------------


def select_best_patch(repo_dir: Path, ledger_dir: Path, num_agents: int) -> str:
    """
    Select the best patch from the swarm's work.

    Priority:
    1. A fix verified by another agent (endorsed)
    2. Multiple fixes — pick the one with most test pass mentions
    3. No verified fix — fall back to the workspace git diff
    """
    endorsements: dict[int, list[str]] = {}

    for agent_i in range(num_agents):
        verification_file = ledger_dir / f"agent-{agent_i}" / "verification.md"
        if not verification_file.exists():
            continue
        content = verification_file.read_text()
        for agent_j in range(num_agents):
            if agent_j == agent_i:
                continue
            if f"agent-{agent_j}" in content.lower() and "pass" in content.lower():
                endorsements.setdefault(agent_j, []).append(f"agent-{agent_i}")

    if endorsements:
        best_agent = max(endorsements, key=lambda k: len(endorsements[k]))
        diff_file = ledger_dir / f"agent-{best_agent}" / "proposed_fix.diff"
        if diff_file.exists():
            diff_content = diff_file.read_text().strip()
            if diff_content:
                logger.info(
                    f"[patch-select] Using endorsed fix from agent-{best_agent} "
                    f"({len(endorsements[best_agent])} endorsements)"
                )
                try:
                    subprocess.run(
                        ["git", "checkout", "."],
                        cwd=str(repo_dir),
                        capture_output=True,
                        timeout=30,
                    )
                    result = subprocess.run(
                        ["git", "apply", "--allow-empty", str(diff_file)],
                        cwd=str(repo_dir),
                        capture_output=True,
                        timeout=30,
                    )
                    if result.returncode == 0:
                        return extract_patch(repo_dir)
                    else:
                        logger.warning(
                            f"[patch-select] Failed to apply endorsed diff: "
                            f"{result.stderr.decode()[:200]}"
                        )
                except Exception as e:
                    logger.warning(f"[patch-select] Error applying endorsed diff: {e}")

    proposed_diffs: list[tuple[int, str]] = []
    for agent_i in range(num_agents):
        diff_file = ledger_dir / f"agent-{agent_i}" / "proposed_fix.diff"
        if diff_file.exists():
            content = diff_file.read_text().strip()
            if content:
                proposed_diffs.append((agent_i, content))

    if proposed_diffs and len(proposed_diffs) == 1:
        agent_i, diff_content = proposed_diffs[0]
        logger.info(f"[patch-select] Using single proposed fix from agent-{agent_i}")
        try:
            subprocess.run(
                ["git", "checkout", "."],
                cwd=str(repo_dir),
                capture_output=True,
                timeout=30,
            )
            diff_file = ledger_dir / f"agent-{agent_i}" / "proposed_fix.diff"
            result = subprocess.run(
                ["git", "apply", "--allow-empty", str(diff_file)],
                cwd=str(repo_dir),
                capture_output=True,
                timeout=30,
            )
            if result.returncode == 0:
                return extract_patch(repo_dir)
            else:
                logger.warning(
                    f"[patch-select] Failed to apply proposed diff: "
                    f"{result.stderr.decode()[:200]}"
                )
        except Exception as e:
            logger.warning(f"[patch-select] Error applying proposed diff: {e}")

    logger.info("[patch-select] Falling back to workspace git diff")
    return extract_patch(repo_dir)


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
    Run the tool I/O perturbation swarm solver on a SWE-bench task.

    Same 3-phase architecture as perturbation_swarm.py, but perturbation
    is applied at the tool output level (PostToolUse hooks on Bash) rather
    than the context level (system prompt injection).

    Controlled by PERTURBATION_INTENSITY env var (0.0-0.20).
    """
    start_time = time.time()
    intensity = float(os.environ.get("PERTURBATION_INTENSITY", "0.0"))

    # Shared perturbation event log — written to disk at the end
    perturbation_log: list[dict] = []

    logger.info(
        f"[{agent_id}] Tool I/O perturbation swarm solver starting "
        f"(intensity={intensity})"
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

    # ------------------------------------------------------------------
    # Phase 0: Plan roles (unperturbed)
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
    # Phase 1: Swarm execution (tool I/O perturbed)
    # ------------------------------------------------------------------
    logger.info(
        f"[{agent_id}] Phase 1: Launching {len(roles)} swarm agents "
        f"with tool I/O perturbation (intensity={intensity})..."
    )

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

    await asyncio.gather(
        *[
            run_swarm_agent(
                agent_num=i,
                role=role,
                task=task,
                repo_dir=repo_dir,
                ledger_dir=ledger_dir,
                num_agents=len(roles),
                config=config,
                intensity=intensity,
                trace_data=agent_trace_datas[i],
                agent_api_key=agent_api_key,
                perturbation_log=perturbation_log,
            )
            for i, role in enumerate(roles)
        ]
    )

    # Aggregate trace data from all swarm agents
    total_turns = 0
    total_cost = 0.0
    all_messages = []
    errors = []
    for atd in agent_trace_datas:
        total_turns += atd.num_turns
        total_cost += atd.total_cost_usd
        all_messages.extend(atd.messages)
        if atd.error:
            errors.append(atd.error)

    trace_data.num_turns = total_turns
    trace_data.total_cost_usd = total_cost
    trace_data.messages = all_messages
    if errors:
        trace_data.error = "; ".join(errors)

    # ------------------------------------------------------------------
    # Write perturbation event log
    # ------------------------------------------------------------------
    events_file = ledger_dir / "perturbation_events.jsonl"
    try:
        with open(events_file, "w") as f:
            for event in perturbation_log:
                f.write(json.dumps(event) + "\n")
        logger.info(
            f"[{agent_id}] Wrote {len(perturbation_log)} perturbation events "
            f"to {events_file}"
        )
    except Exception as e:
        logger.warning(f"[{agent_id}] Failed to write perturbation events: {e}")

    # ------------------------------------------------------------------
    # Phase 2: Select best patch (unperturbed)
    # ------------------------------------------------------------------
    logger.info(f"[{agent_id}] Phase 2: Selecting best patch...")
    patch = select_best_patch(repo_dir, ledger_dir, len(roles))
    trace_data.patch_produced = bool(patch.strip())
    trace_data.patch_content = patch

    elapsed = time.time() - start_time

    # Compute perturbation metrics
    test_commands_total = sum(1 for e in perturbation_log if e.get("is_test_command"))
    unique_command_hashes = len(
        set(e.get("command_hash", "") for e in perturbation_log)
    )
    test_reruns = test_commands_total - unique_command_hashes

    logger.info(
        f"[{agent_id}] Finished in {elapsed:.1f}s, "
        f"patch={'yes' if patch.strip() else 'no'} "
        f"({len(patch)} bytes), "
        f"total_turns={total_turns}, total_cost=${total_cost:.4f}, "
        f"perturbation_events={len(perturbation_log)}, "
        f"test_commands={test_commands_total}, "
        f"test_reruns={test_reruns}"
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
        "perturbation_intensity": intensity,
        "perturbation_type": "tool_io",
        "roles": [r["name"] for r in roles],
        # v0.2 metrics
        "perturbation_events": len(perturbation_log),
        "test_commands_total": test_commands_total,
        "test_reruns": test_reruns,
    }


__all__ = ["solve_swe_task"]
