"""
Self-Organizing Perturbation Swarm Solver.

Implements a heterarchical swarm of agents that self-organize to solve
SWE-bench tasks through:
  1. Live communication via SwarmBus (in-memory message bus + filesystem ledger)
  2. Dynamic coordination with role planning and automatic context injection
  3. Beads (bd) dependency management for structured work item tracking
  4. Test-driven verification and cross-agent endorsement
  5. Optional ChatOverflow integration for cross-run knowledge

Perturbation: Context perturbation via uncertainty injection into agent
system prompts. Controlled by PERTURBATION_INTENSITY env var (0.0-0.20).

Architecture:
  Phase 0: PLANNING — single query() call plans 2-4 roles + deps + design
  Phase 1: SWARM EXECUTION — N agents in parallel, shared workspace + bus + beads
  Phase 2: PATCH SELECTION — pick the most-verified fix from ledger + beads status
"""

import asyncio
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
)

from ..config import HarnessConfig
from ..solver_agent import (
    CHATOVERFLOW_SWE_SKILL_PROMPT,
    extract_patch,
    setup_workspace,
)
from ..task_selector import SWETask
from ..tracing import AgentTraceData
from .._sdk_patches import patch_sdk_mcp_close
from ..swarm_bus import SwarmBus
from ..swarm_hooks import build_swarm_hooks
from ..swarm_beads import (
    BeadsTracker,
    build_swarm_mcp_server,
    create_role_tasks,
    SWARM_MCP_TOOL_NAMES,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SWARM_PROTOCOL_PROMPT = """
You are agent-{agent_num} ({role_name}) in a LIVE swarm of {num_agents} agents working together to solve a GitHub issue.

## How Communication Works

1. **Automatic updates**: Every few tool calls, you will receive a SWARM STATUS UPDATE
   injected into your context. This shows what every other agent is doing, their recent
   findings, and their current status. READ THESE CAREFULLY and adapt your approach.

2. **Active communication tools**: You have MCP tools for explicit communication:
   - swarm_broadcast: Send an important finding to all agents
   - swarm_read_updates: Pull latest messages from teammates
   - swarm_ready: See what work items are unblocked (beads)
   - swarm_claim_task: Claim a work item so others don't duplicate it
   - swarm_create_task: Create new work when you discover something
   - swarm_add_dep: Link dependencies between work items
   - swarm_complete_task: Mark work as done (unblocks dependent tasks)
   - swarm_blocked: See what's waiting on what

3. **Dependency tracking**: Work items are tracked with beads (bd). When you complete
   a task, dependent tasks automatically become available. Check swarm_ready before
   starting new work to see what's unblocked.

## Swarm Design

{swarm_design_text}

## Ownership Rules

- When you claim a task via swarm_claim_task, YOU OWN IT. Others should not work on it.
- If you discover that your task is blocked, create a blocking dependency and move on.
- If you're idle (all your tasks are done or blocked), check swarm_ready for unclaimed work.
- If another agent's approach contradicts yours, broadcast your evidence and defer to
  whoever has stronger test-backed evidence.
- The agent with the most verified test passes has the strongest authority on the fix.

## Swarm Ledger (Filesystem)

You also have a shared filesystem ledger for persistent artifacts:

- Write your findings to: swarm_ledger/agent-{agent_num}/findings.md
- Read others' findings: check swarm_ledger/agent-*/findings.md
- Post your status: write "exploring" / "fixing" / "verifying" / "done" to swarm_ledger/agent-{agent_num}/status.md
- Propose a fix: write your diff to swarm_ledger/agent-{agent_num}/proposed_fix.diff (use `git diff > swarm_ledger/agent-{agent_num}/proposed_fix.diff`)
- Verify others: apply their diff, run tests, write results to swarm_ledger/agent-{agent_num}/verification.md

## Coordination Rules

- When you see a SWARM STATUS UPDATE, acknowledge what others found and adapt
- Before investigating a file, check if another agent is already working on it
- Use swarm_broadcast for important discoveries (root cause found, fix proposed, tests passing)
- Use swarm_create_task + swarm_add_dep when you discover prerequisite work
- Do NOT duplicate work another agent is already doing — move to verification or a different angle
- When claiming ownership, broadcast: "I own [task]. Working on [file/area]."

## Conflict Handling

If an edit fails because the file changed (another agent edited it), re-read the file
and check updates (swarm_read_updates) to understand what changed before retrying.

## Your Suggested Focus

{role_goal}

This is a starting point. Adapt based on what you and others discover.

## Important Rules
- The repo is already cloned at the correct commit in your working directory
- Make changes directly -- do NOT create branches or commits
- Make **minimal, focused changes** -- only fix what the issue describes
- Do NOT add tests unless the issue specifically asks for them
- Do NOT modify test files unless the issue is about a test

## Test Verification — MANDATORY
After implementing or reviewing a fix, you MUST run the project's actual test suite:
1. Find the test file for the module you changed (look in `tests/` for a file matching the module name)
2. Run it: `python -m pytest <test_file> -x -q` (or the project's test runner)
3. If tests fail, read the failures carefully, fix your code, and re-run
4. Broadcast the test results: "Tests PASS: <test_file>" or "Tests FAIL: <failing test names>"
5. Do NOT assume your fix is correct without running the actual test suite
6. Do NOT write your own standalone reproduction scripts INSTEAD of running the real tests — do both

If you are a reproducer/analyst (not the fixer), run the existing tests BEFORE any fix is applied to confirm which tests fail, then broadcast the failing test names so the fixer knows what to target.

## Edge-Case Testing — MANDATORY
Your fix will be evaluated against HIDDEN tests you cannot see. To maximize the chance of
passing them, you MUST write and run your own edge-case tests BEFORE finalizing:

1. **Re-read the problem statement word by word.** Extract EVERY concrete behavior it describes.
   Pay attention to phrases like "should also", "in addition", "when X is None/empty/missing".
2. **Write a small test script** (`/tmp/test_edge_cases.py`) that covers:
   - The exact scenario from the problem statement
   - The boundary/None/empty/default case (e.g., what if the argument is missing?)
   - The interaction case (e.g., does the fix still work when combined with related features?)
3. **Run your edge-case tests** and fix until they all pass.
4. **Broadcast your edge-case findings** so other agents can verify.

## Fix Self-Review — MANDATORY
After implementing your fix AND running tests, do a critical self-review before stopping:

1. **Re-read the problem statement LINE BY LINE**. Does your fix address EVERY behavior described?
   Many issues describe multiple requirements — fixing one while missing another is a common failure.
   Ask: "If someone wrote a test for each sentence in this issue, would my fix pass all of them?"
2. **Consider deletion**. Could the bug be caused by code that SHOULDN'T EXIST? Sometimes
   the correct fix is to remove a method, condition, or override — not to add or change code.
   Ask: "What happens if this code simply wasn't here? Does the parent class, fallback path,
   or default behavior already do the right thing?"
3. **Fewer lines = higher confidence**. A 1-line deletion that fixes the issue is more likely
   correct than a 20-line addition. If your fix is large, ask if there's a simpler approach.
4. **Rate your confidence** (1-5) and broadcast it:
   - 5: Tests pass, fix is minimal, directly addresses root cause
   - 4: Tests pass, fix works but I'm not 100% sure it's the best approach
   - 3: Most tests pass, or fix works but feels over-engineered
   - 2: Some tests fail, or I'm patching a symptom not the cause
   - 1: Tests fail, approach may be wrong
5. **If confidence ≤ 3**, try at least one alternative approach before stopping:
   - What if you removed code instead of adding it?
   - What if the existing code already handles this and something is interfering?
   - What is the simplest possible change that would fix this?

## Efficiency Rules — CRITICAL
- **DO NOT duplicate work**. Before reading a file, check swarm_read_updates to see if another agent already analyzed it.
- **STOP when the fix is verified**. Once the fix is applied and tests pass, broadcast success and STOP. Do not keep exploring.
- When another agent broadcasts that tests pass and the fix is applied, **verify their fix by running the tests yourself** and STOP.
- If you receive a SWARM STATUS UPDATE showing another agent already fixed the issue, run the tests to verify and STOP.
- Your goal is to contribute UNIQUE value. If your role's work is done, STOP immediately.

## Beads Work Items

{beads_info}
{perturbation_text}{chatoverflow_prompt}
"""

# Swarm design text templates
SWARM_DESIGNS = {
    "flat": (
        "**Design: Flat (Peer)**\n"
        "All agents are peers. No hierarchy. First to reproduce and fix wins. "
        "Others verify. Anyone can claim any unblocked task."
    ),
    "coordinator": (
        "**Design: Coordinator (Emergent)**\n"
        "The agent who first identifies the root cause becomes de-facto coordinator. "
        "Others defer unless they find contradicting evidence. "
        "Coordinator broadcasts 'I am coordinating' and decomposes remaining work."
    ),
}

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

DEFAULT_DEPENDENCIES = [
    ["root_cause_tracer", "bug_reproducer"],
    ["solution_architect", "root_cause_tracer"],
]

PLANNER_PROMPT = """Analyze this GitHub issue and decide what specialist roles a swarm of agents should take to solve it.

Consider the nature of the bug: is it a logic error, a missing feature, a race condition, a type error, etc.?
What different angles would help solve it faster?

Output a JSON object with these fields:
- "roles": array of 2-4 roles, each with "name" (snake_case) and "goal" (one sentence)
- "dependencies": array of [from_role, to_role] pairs where from_role depends on to_role
  (i.e., to_role must finish before from_role can start)
- "swarm_design": one of "flat", "coordinator", or "lead:<role_name>"
  - "flat": all agents are peers, no hierarchy
  - "coordinator": the root-cause finder becomes coordinator
  - "lead:<role_name>": the named role leads and decomposes work for others

Output ONLY the JSON object, no other text.

Example output:
{
  "roles": [
    {"name": "test_runner", "goal": "Find and run failing tests to reproduce the exact error."},
    {"name": "code_tracer", "goal": "Trace the error path through the source to find the root cause."},
    {"name": "fix_implementer", "goal": "Implement and verify a minimal fix once the root cause is identified."}
  ],
  "dependencies": [
    ["code_tracer", "test_runner"],
    ["fix_implementer", "code_tracer"]
  ],
  "swarm_design": "coordinator"
}
"""

# Maximum turns per swarm agent (lower than default since workload is shared)
SWARM_AGENT_MAX_TURNS = 30

# Maximum turns for the planner (lightweight, read-only)
PLANNER_MAX_TURNS = 5


# ---------------------------------------------------------------------------
# Phase 0: Plan roles
# ---------------------------------------------------------------------------


async def plan_roles(
    task: SWETask, repo_dir: Path, config: HarnessConfig
) -> dict:
    """
    Run a single lightweight planner agent to decide swarm roles, deps, and design.

    Uses query() with read-only tools and max_turns=5.
    On parse failure, returns defaults.

    Returns:
        A dict with "roles", "dependencies", and "swarm_design" keys.
    """
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
        setting_sources=["user"],
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
        logger.warning(f"[planner] Failed: {e}, using defaults")
        return {
            "roles": DEFAULT_ROLES,
            "dependencies": DEFAULT_DEPENDENCIES,
            "swarm_design": "flat",
        }

    # Parse JSON from the last assistant text
    result = _parse_planner_json(last_text)
    if result:
        logger.info(
            f"[planner] Planned {len(result['roles'])} roles: "
            f"{[r['name'] for r in result['roles']]}, "
            f"design={result['swarm_design']}, "
            f"deps={result['dependencies']}"
        )
        return result

    logger.warning("[planner] Could not parse planner output, using defaults")
    return {
        "roles": DEFAULT_ROLES,
        "dependencies": DEFAULT_DEPENDENCIES,
        "swarm_design": "flat",
    }


def _parse_planner_json(text: str) -> dict | None:
    """Extract and validate planner JSON output (object or array)."""
    # Try to find a JSON object first
    obj_match = re.search(r'\{.*\}', text, re.DOTALL)
    if obj_match:
        try:
            data = json.loads(obj_match.group())
            if isinstance(data, dict) and "roles" in data:
                roles = data["roles"]
                if _validate_roles(roles):
                    deps = data.get("dependencies", [])
                    design = data.get("swarm_design", "flat")
                    return {
                        "roles": roles,
                        "dependencies": deps if isinstance(deps, list) else [],
                        "swarm_design": design if isinstance(design, str) else "flat",
                    }
        except json.JSONDecodeError:
            pass

    # Fall back to array-only format (backwards compat)
    arr_match = re.search(r'\[.*\]', text, re.DOTALL)
    if arr_match:
        try:
            roles = json.loads(arr_match.group())
            if _validate_roles(roles):
                return {
                    "roles": roles,
                    "dependencies": DEFAULT_DEPENDENCIES,
                    "swarm_design": "flat",
                }
        except json.JSONDecodeError:
            pass

    return None


def _validate_roles(roles: list) -> bool:
    """Validate a roles list structure."""
    if not isinstance(roles, list) or len(roles) < 2 or len(roles) > 4:
        return False
    for role in roles:
        if not isinstance(role, dict):
            return False
        if "name" not in role or "goal" not in role:
            return False
        if not isinstance(role["name"], str) or not isinstance(role["goal"], str):
            return False
    return True


# ---------------------------------------------------------------------------
# Phase 1: Swarm execution
# ---------------------------------------------------------------------------


def _get_swarm_design_text(design: str, roles: list[dict]) -> str:
    """Build the swarm design text for the system prompt."""
    if design in SWARM_DESIGNS:
        return SWARM_DESIGNS[design]

    if design.startswith("lead:"):
        lead_role = design[5:]
        return (
            f"**Design: Lead ({lead_role})**\n"
            f"The '{lead_role}' role leads and owns the final fix decision. "
            f"Other agents feed findings TO the lead. "
            f"Lead decomposes work via swarm_create_task."
        )

    # Custom design: inject verbatim
    return f"**Design: Custom**\n{design}"


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
    bus: SwarmBus,
    tracker: BeadsTracker,
    role_task_ids: dict[str, str],
    swarm_design: str,
    roles: list[dict],
) -> None:
    """
    Run a single swarm agent with shared workspace, bus, and beads.

    The agent gets:
    - A role suggestion (starting point, not rigid)
    - Access to the shared repo directory
    - Real-time communication via SwarmBus (injected automatically)
    - Beads work item tracking via MCP tools
    - Perturbation text injected into system prompt
    - Optional ChatOverflow access
    """
    # Select perturbation text for the closest intensity level
    perturbation_text = _get_perturbation_text(intensity)

    # Build ChatOverflow prompt if enabled
    chatoverflow_prompt = ""
    if config.enable_chatoverflow:
        chatoverflow_prompt = "\n" + CHATOVERFLOW_SWE_SKILL_PROMPT.format(
            chatoverflow_api_url=config.chatoverflow_api_url,
        )

    # Build beads info string
    beads_info = ""
    if role_task_ids:
        my_task_id = role_task_ids.get(role["name"], "")
        beads_lines = ["Your assigned beads task ID: " + (my_task_id or "none")]
        beads_lines.append("All role task IDs:")
        for rname, tid in role_task_ids.items():
            beads_lines.append(f"  - {rname}: {tid}")
        beads_lines.append(
            "\nUse swarm_claim_task to claim your task when you start working, "
            "and swarm_complete_task when done."
        )
        beads_info = "\n".join(beads_lines)

    # Build swarm design text
    swarm_design_text = _get_swarm_design_text(swarm_design, roles)

    # Build the system prompt
    system_prompt = SWARM_PROTOCOL_PROMPT.format(
        agent_num=agent_num,
        role_name=role["name"],
        num_agents=num_agents,
        role_goal=role["goal"],
        swarm_design_text=swarm_design_text,
        beads_info=beads_info,
        perturbation_text=perturbation_text,
        chatoverflow_prompt=chatoverflow_prompt,
    )

    # Build environment variables
    env = {}
    if config.enable_chatoverflow and agent_api_key:
        env["CHATOVERFLOW_API_URL"] = config.chatoverflow_api_url
        env["CHATOVERFLOW_API_KEY"] = agent_api_key

    # Build hooks (swarm-aware, replaces plain tracing hooks)
    # inject_every=3: agents learn about teammates faster, reducing duplicate work
    hooks = build_swarm_hooks(bus, agent_num, trace_data, inject_every=3)

    # Build MCP server for swarm tools
    mcp_servers: dict = {}
    allowed_tools = ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]

    if tracker.available:
        swarm_server = build_swarm_mcp_server(bus, tracker, agent_num)
        mcp_servers["swarm"] = swarm_server
        allowed_tools.extend(SWARM_MCP_TOOL_NAMES)

    options = ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": system_prompt,
        },
        model=config.model,
        permission_mode="bypassPermissions",
        cwd=str(repo_dir),
        allowed_tools=allowed_tools,
        setting_sources=["user"],
        env=env,
        max_turns=SWARM_AGENT_MAX_TURNS,
        hooks=hooks,
        mcp_servers=mcp_servers,
    )

    prompt = f"""## GitHub Issue to Solve

**Repository:** {task.repo}
**Instance ID:** {task.instance_id}

### Problem Statement

{task.problem_statement}

---

The repository is already cloned in your working directory and checked out at commit `{task.base_commit}`.

You are agent-{agent_num} (role: {role['name']}). Your initial focus: {role['goal']}

The swarm ledger is at `swarm_ledger/` in the repo directory. Your ledger directory is `swarm_ledger/agent-{agent_num}/`.

**Start by**: Use swarm_claim_task to claim your assigned task, then begin work.
Use swarm_broadcast to share important findings with teammates.
Check swarm_read_updates or wait for automatic status updates to coordinate.

Explore the repository, understand the code, coordinate with other agents, and fix the issue.
Make minimal changes, do not create branches or commits, just edit the files directly.
"""

    agent_label = f"swarm-agent-{agent_num}"
    trace_data.prompt = prompt

    # Register role on bus and post initial status
    bus.set_role(agent_num, role["name"])
    await bus.update_status(agent_num, "exploring")
    await bus.post(
        agent_num, "status", f"Starting as {role['name']}: {role['goal']}"
    )

    logger.info(
        f"[{agent_label}] Starting (role: {role['name']}, intensity: {intensity})"
    )

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                content_dicts = []
                for block in message.content:
                    if isinstance(block, TextBlock):
                        content_dicts.append(
                            {"type": "text", "text": block.text}
                        )
                        if len(block.text) > 100:
                            logger.debug(
                                f"[{agent_label}] text: {block.text[:100]}..."
                            )
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
                                    "content": (
                                        str(block.content)[:2000]
                                        if block.content
                                        else ""
                                    ),
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

    # Update bus status to done
    await bus.update_status(agent_num, "done")


def _get_perturbation_text(intensity: float) -> str:
    """Get the perturbation prompt text for the given intensity level."""
    if intensity <= 0.0:
        return ""
    # Find the closest defined level at or below the given intensity
    levels = sorted(PERTURBATION_PROMPTS.keys())
    selected = 0.0
    for level in levels:
        if level <= intensity:
            selected = level
    return PERTURBATION_PROMPTS.get(selected, "")


# ---------------------------------------------------------------------------
# Phase 2: Patch selection
# ---------------------------------------------------------------------------


def select_best_patch(
    repo_dir: Path,
    ledger_dir: Path,
    num_agents: int,
    tracker: BeadsTracker | None = None,
) -> str:
    """
    Select the best patch from the swarm's work.

    Priority:
    1. A fix verified by another agent (endorsed) — apply that agent's diff
    2. Multiple fixes — pick the one with most test pass mentions
    3. No verified fix — fall back to the workspace git diff

    Returns the patch string.
    """
    # Scan verification files to find endorsed fixes
    endorsements: dict[int, list[str]] = {}  # agent_num -> list of endorser texts

    for agent_i in range(num_agents):
        verification_file = ledger_dir / f"agent-{agent_i}" / "verification.md"
        if not verification_file.exists():
            continue
        content = verification_file.read_text()
        # Look for references to other agents' fixes that PASS
        for agent_j in range(num_agents):
            if agent_j == agent_i:
                continue
            # Check if this agent verified agent_j's fix as passing
            if (
                f"agent-{agent_j}" in content.lower()
                and "pass" in content.lower()
            ):
                endorsements.setdefault(agent_j, []).append(f"agent-{agent_i}")

    if endorsements:
        # Pick the agent with most endorsements
        best_agent = max(endorsements, key=lambda k: len(endorsements[k]))
        diff_file = ledger_dir / f"agent-{best_agent}" / "proposed_fix.diff"
        if diff_file.exists():
            diff_content = diff_file.read_text().strip()
            if diff_content:
                logger.info(
                    f"[patch-select] Using endorsed fix from agent-{best_agent} "
                    f"({len(endorsements[best_agent])} endorsements)"
                )
                # Apply the endorsed diff and return the resulting workspace diff
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
                    logger.warning(
                        f"[patch-select] Error applying endorsed diff: {e}"
                    )

    # Check for any proposed fix diffs
    proposed_diffs: list[tuple[int, str]] = []
    for agent_i in range(num_agents):
        diff_file = ledger_dir / f"agent-{agent_i}" / "proposed_fix.diff"
        if diff_file.exists():
            content = diff_file.read_text().strip()
            if content:
                proposed_diffs.append((agent_i, content))

    if proposed_diffs and len(proposed_diffs) == 1:
        # Single proposed diff — apply it
        agent_i, diff_content = proposed_diffs[0]
        logger.info(
            f"[patch-select] Using single proposed fix from agent-{agent_i}"
        )
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
            logger.warning(
                f"[patch-select] Error applying proposed diff: {e}"
            )

    # Fall back to the workspace git diff (whatever state the agents left it in)
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
    Run the perturbation swarm solver on a SWE-bench task.

    This is the entry point called by the harness. It orchestrates:
      Phase 0: Plan roles + deps + design (single lightweight agent)
      Phase 1: Launch swarm agents in parallel (shared workspace + bus + beads)
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
    # Apply SDK monkey-patch for MCP shutdown bug (safe to call multiple times)
    patch_sdk_mcp_close()

    start_time = time.time()
    intensity = float(os.environ.get("PERTURBATION_INTENSITY", "0.0"))

    logger.info(
        f"[{agent_id}] Perturbation swarm solver starting "
        f"(intensity={intensity}, swarm_design={config.swarm_design})"
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
    # Phase 0: Plan roles + deps + design
    # ------------------------------------------------------------------
    logger.info(f"[{agent_id}] Phase 0: Planning roles...")
    plan = await plan_roles(task, repo_dir, config)
    roles = plan["roles"]
    dependencies = plan["dependencies"]

    # Determine swarm design: use config if not "auto", otherwise use planner's
    swarm_design = config.swarm_design
    if swarm_design == "auto":
        swarm_design = plan.get("swarm_design", "flat")

    logger.info(
        f"[{agent_id}] Phase 0: Planned {len(roles)} roles: "
        f"{[r['name'] for r in roles]}, design={swarm_design}, "
        f"deps={dependencies}"
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
    # Initialize SwarmBus
    # ------------------------------------------------------------------
    bus = SwarmBus(num_agents=len(roles), ledger_dir=ledger_dir)

    # ------------------------------------------------------------------
    # Initialize Beads
    # ------------------------------------------------------------------
    tracker = BeadsTracker(repo_dir)
    role_task_ids: dict[str, str] = {}

    if tracker.available:
        initialized = await tracker.init(prefix="swarm")
        if initialized:
            role_task_ids = await create_role_tasks(
                tracker, roles, dependencies
            )
            logger.info(
                f"[{agent_id}] Beads initialized: {role_task_ids}"
            )
        else:
            logger.warning(f"[{agent_id}] Beads init failed, continuing without")
    else:
        logger.info(f"[{agent_id}] bd binary not available, skipping beads")

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
                bus=bus,
                tracker=tracker,
                role_task_ids=role_task_ids,
                swarm_design=swarm_design,
                roles=roles,
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
    # Phase 2: Select best patch
    # ------------------------------------------------------------------
    logger.info(f"[{agent_id}] Phase 2: Selecting best patch...")
    patch = select_best_patch(repo_dir, ledger_dir, len(roles), tracker)
    trace_data.patch_produced = bool(patch.strip())
    trace_data.patch_content = patch

    elapsed = time.time() - start_time
    logger.info(
        f"[{agent_id}] Finished in {elapsed:.1f}s, "
        f"patch={'yes' if patch.strip() else 'no'} "
        f"({len(patch)} bytes), "
        f"total_turns={total_turns}, total_cost=${total_cost:.4f}"
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
        "swarm_design": swarm_design,
        "roles": [r["name"] for r in roles],
    }


__all__ = ["solve_swe_task"]
