"""
Oracle Swarm Solver -- extends the perturbation swarm with oracle verification.

Inner loop per task:
  Phase 0: Plan roles (reuses perturbation_swarm planner)
  Phase 0.5: Inject oracle roles (one per enabled OracleStrategy)
  Phase 1: Swarm execution (coding agents + oracle agents in parallel)
  Phase 2: Post-swarm oracle check (run oracle artifacts against the fix)
  Phase 3: If oracle checks fail, run another swarm round with feedback
  Phase 4: Select best patch

The solver accepts lessons_text and oracle strategies from the self-improving
harness, allowing the waypoint coordinator to tune behavior across epochs.
"""

import asyncio
import logging
import os
import time
from pathlib import Path

from ..config import HarnessConfig
from ..oracle_bridge import (
    DEFAULT_ORACLE_STRATEGIES,
    OracleStrategy,
    format_oracle_feedback,
    run_oracle_checks,
)
from ..solver_agent import (
    extract_patch,
    setup_workspace,
)
from ..task_selector import SWETask
from ..tracing import AgentTraceData
from .._sdk_patches import patch_sdk_mcp_close
from ..swarm_bus import SwarmBus
from ..swarm_beads import (
    BeadsTracker,
    create_role_tasks,
    SWARM_MCP_TOOL_NAMES,
)

# Reuse core swarm functions from perturbation_swarm
from .perturbation_swarm import (
    plan_roles,
    run_swarm_agent,
    select_best_patch,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Oracle-specific role prompt
# ---------------------------------------------------------------------------

ORACLE_ROLE_PROMPT = """
You are agent-{{agent_num}} ({{role_name}}) in a LIVE swarm of {{num_agents}} agents.

## Your Mission
You are an ORACLE GENERATOR. Your job is NOT to fix the bug -- it's to generate
verification tests that the fix must pass.

## How You Work
1. Read the problem statement carefully
2. Explore the codebase to understand the affected modules
3. Generate test files in `oracle_tests/{{strategy_name}}/`
4. Post to the swarm: "Oracle tests ready at oracle_tests/{{strategy_name}}/"
5. Other agents will run your tests to verify their fix

## Strategy: {{strategy_description}}

## Test Quality
- Tests MUST be runnable with `pytest <file>` (or bash for behavioral checks)
- Tests MUST import from the codebase correctly
- Tests MUST be deterministic
- Tests SHOULD cover the main fix and at least one edge case
- Do NOT modify the codebase -- only write test files

## Swarm Communication
You have the same swarm tools as other agents (swarm_broadcast, swarm_read_updates, etc.).
Use swarm_broadcast to announce when your oracle tests are ready.

{{addendum}}

## Important
- Do NOT attempt to fix the bug. That's other agents' job.
- Do NOT create tests that depend on the fix being applied -- test the EXPECTED behavior.
- After generating tests, STOP. Your work is done.
"""


# ---------------------------------------------------------------------------
# Inner loop: swarm + oracle multi-round
# ---------------------------------------------------------------------------


def _inject_oracle_roles(
    roles: list[dict],
    dependencies: list[list[str]],
    strategies: list[OracleStrategy],
) -> tuple[list[dict], list[list[str]]]:
    """Inject oracle generator roles into the planner's role list.

    Oracle roles have no dependencies (they start immediately).
    Coding roles do NOT depend on oracle roles (they run in parallel).
    """
    existing_names = {r["name"] for r in roles}
    new_roles = list(roles)
    new_deps = list(dependencies)

    for strategy in strategies:
        if not strategy.enabled:
            continue
        role_name = f"oracle_{strategy.name}"
        if role_name in existing_names:
            continue
        new_roles.append({
            "name": role_name,
            "goal": (
                f"Generate {strategy.name} oracle verification tests. "
                f"{strategy.description}. "
                f"Write tests to oracle_tests/{strategy.name}/. "
                f"Do NOT fix the bug -- only write verification tests."
            ),
        })

    return new_roles, new_deps


def _build_oracle_agent_prompt(
    strategy: OracleStrategy,
    agent_num: int,
    num_agents: int,
) -> str:
    """Build a system prompt for an oracle generator swarm agent."""
    return ORACLE_ROLE_PROMPT.replace(
        "{{agent_num}}", str(agent_num)
    ).replace(
        "{{role_name}}", f"oracle_{strategy.name}"
    ).replace(
        "{{num_agents}}", str(num_agents)
    ).replace(
        "{{strategy_name}}", strategy.name
    ).replace(
        "{{strategy_description}}", strategy.description
    ).replace(
        "{{addendum}}", strategy.prompt_addendum or ""
    )


async def _run_swarm_round(
    round_num: int,
    task: SWETask,
    repo_dir: Path,
    ledger_dir: Path,
    roles: list[dict],
    dependencies: list[list[str]],
    swarm_design: str,
    config: HarnessConfig,
    trace_data: AgentTraceData,
    agent_api_key: str,
    agent_id: str,
    lessons_text: str,
    oracle_feedback: str,
    strategies: list[OracleStrategy],
) -> list[AgentTraceData]:
    """Run one round of the swarm (coding agents + oracle agents)."""
    intensity = float(os.environ.get("PERTURBATION_INTENSITY", "0.0"))
    num_agents = len(roles)

    # Initialize swarm infrastructure
    bus = SwarmBus(num_agents=num_agents, ledger_dir=ledger_dir)
    tracker = BeadsTracker(repo_dir)
    role_task_ids: dict[str, str] = {}

    if tracker.available:
        prefix = f"swarm-r{round_num}"
        initialized = await tracker.init(prefix=prefix)
        if initialized:
            role_task_ids = await create_role_tasks(tracker, roles, dependencies)
            logger.info(f"[{agent_id}] Round {round_num}: Beads initialized")

    # Initialize ledger directories
    for i in range(num_agents):
        agent_ledger = ledger_dir / f"agent-{i}"
        agent_ledger.mkdir(parents=True, exist_ok=True)
        (agent_ledger / "status.md").write_text("exploring")
        (agent_ledger / "findings.md").write_text(
            f"# Agent-{i} Findings ({roles[i]['name']})\n\n"
        )

    # Create oracle test directories
    oracle_tests_dir = repo_dir / "oracle_tests"
    oracle_tests_dir.mkdir(parents=True, exist_ok=True)
    for strategy in strategies:
        if strategy.enabled:
            (oracle_tests_dir / strategy.name).mkdir(parents=True, exist_ok=True)

    # Build per-agent trace data
    agent_trace_datas = []
    for i in range(num_agents):
        atd = AgentTraceData(
            agent_id=f"{agent_id}-r{round_num}-{i}",
            instance_id=task.instance_id,
            agent_num=i,
            iteration=trace_data.iteration,
            model=config.model,
        )
        agent_trace_datas.append(atd)

    # Build extra context for round > 0
    extra_context = ""
    if round_num > 0 and oracle_feedback:
        extra_context = (
            f"\n## Oracle Feedback from Round {round_num - 1}\n\n"
            f"{oracle_feedback}\n\n"
            "The previous round's fix did not pass all oracle checks. "
            "Review the failures above and fix the remaining issues.\n"
        )

    if lessons_text:
        extra_context += (
            f"\n## Lessons from Previous Epochs\n\n{lessons_text}\n"
        )

    # Launch all agents in parallel
    logger.info(
        f"[{agent_id}] Round {round_num}: "
        f"Launching {num_agents} agents ({[r['name'] for r in roles]})"
    )

    await asyncio.gather(
        *[
            run_swarm_agent(
                agent_num=i,
                role=role,
                task=task,
                repo_dir=repo_dir,
                ledger_dir=ledger_dir,
                num_agents=num_agents,
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

    return agent_trace_datas


async def solve_swe_task(
    task: SWETask,
    agent_id: str,
    workspace_dir: Path,
    ref_repo_dir: Path,
    config: HarnessConfig,
    trace_data: AgentTraceData,
    agent_api_key: str = "",
    lessons_text: str = "",
    oracle_strategies: list[OracleStrategy] | None = None,
    max_oracle_rounds: int = 2,
) -> dict:
    """Run the oracle swarm solver on a SWE-bench task.

    This is the inner loop:
      Phase 0: Plan roles + inject oracle roles
      Phase 1-N: Run swarm rounds with oracle feedback
      Final: Select best patch

    Args:
        task: The SWE-bench task to solve.
        agent_id: Unique agent identifier.
        workspace_dir: Isolated workspace directory.
        ref_repo_dir: Pre-cloned reference repo to copy from.
        config: Harness configuration.
        trace_data: Tracing data accumulator.
        agent_api_key: Optional ChatOverflow API key.
        lessons_text: Accumulated lessons from prior epochs.
        oracle_strategies: Oracle strategies to use.
        max_oracle_rounds: Max swarm rounds with oracle feedback.

    Returns:
        Dict with instance_id, model_patch, and metadata.
    """
    patch_sdk_mcp_close()
    start_time = time.time()

    if oracle_strategies is None:
        oracle_strategies = DEFAULT_ORACLE_STRATEGIES

    logger.info(
        f"[{agent_id}] Oracle swarm solver starting "
        f"(strategies={[s.name for s in oracle_strategies if s.enabled]}, "
        f"max_rounds={max_oracle_rounds})"
    )

    # Setup workspace
    try:
        repo_dir = await asyncio.to_thread(
            setup_workspace, task, workspace_dir, ref_repo_dir
        )
    except Exception as e:
        logger.error(f"[{agent_id}] Failed to setup workspace: {e}")
        trace_data.error = f"workspace_setup: {e}"
        return {
            "instance_id": task.instance_id,
            "model_name_or_path": f"kekule-oracle-swarm-{config.model}",
            "model_patch": "",
            "agent_id": agent_id,
            "error": str(e),
        }

    ledger_dir = repo_dir / "swarm_ledger"

    # Phase 0: Plan roles
    logger.info(f"[{agent_id}] Phase 0: Planning roles...")
    plan = await plan_roles(task, repo_dir, config)
    coding_roles = plan["roles"]
    dependencies = plan["dependencies"]

    swarm_design = config.swarm_design
    if swarm_design == "auto":
        swarm_design = plan.get("swarm_design", "flat")

    # Phase 0.5: Inject oracle roles
    all_roles, all_deps = _inject_oracle_roles(
        coding_roles, dependencies, oracle_strategies
    )

    logger.info(
        f"[{agent_id}] Roles: {[r['name'] for r in all_roles]} "
        f"(design={swarm_design})"
    )

    # Phase 1-N: Swarm rounds with oracle feedback
    all_trace_datas: list[AgentTraceData] = []
    oracle_feedback = ""
    oracle_results_history: list[dict] = []
    final_patch = ""

    for round_num in range(max_oracle_rounds):
        logger.info(
            f"[{agent_id}] === Round {round_num + 1}/{max_oracle_rounds} ==="
        )

        # Run the swarm round
        round_traces = await _run_swarm_round(
            round_num=round_num,
            task=task,
            repo_dir=repo_dir,
            ledger_dir=ledger_dir,
            roles=all_roles,
            dependencies=all_deps,
            swarm_design=swarm_design,
            config=config,
            trace_data=trace_data,
            agent_api_key=agent_api_key,
            agent_id=agent_id,
            lessons_text=lessons_text,
            oracle_feedback=oracle_feedback,
            strategies=oracle_strategies,
        )
        all_trace_datas.extend(round_traces)

        # Extract current patch
        current_patch = select_best_patch(
            repo_dir, ledger_dir, len(all_roles)
        )

        if not current_patch.strip():
            logger.warning(
                f"[{agent_id}] Round {round_num}: No patch produced"
            )
            if round_num < max_oracle_rounds - 1:
                oracle_feedback = (
                    "WARNING: No patch was produced in the previous round. "
                    "Ensure a fix is applied to the codebase."
                )
                continue
            break

        final_patch = current_patch

        # Run oracle checks against the current fix
        oracle_test_dir = repo_dir / "oracle_tests"
        artifact_paths: dict[str, Path] = {}

        for strategy in oracle_strategies:
            if not strategy.enabled:
                continue
            strategy_dir = oracle_test_dir / strategy.name
            if not strategy_dir.exists():
                continue
            # Find generated artifacts
            if strategy.execution_mode == "pytest":
                for f in strategy_dir.glob("test_*.py"):
                    artifact_paths[strategy.name] = f
                    break
            elif strategy.execution_mode == "bash":
                for f in strategy_dir.glob("check_*.sh"):
                    artifact_paths[strategy.name] = f
                    break

        if not artifact_paths:
            logger.info(
                f"[{agent_id}] Round {round_num}: "
                "No oracle artifacts found, accepting patch"
            )
            break

        # Execute oracle checks
        oracle_results = await run_oracle_checks(
            artifact_paths=artifact_paths,
            strategies=oracle_strategies,
            repo_dir=repo_dir,
        )

        oracle_results_history.append({
            "round": round_num,
            "results": {
                name: {"passed": r.passed, "evidence": r.evidence[:500]}
                for name, r in oracle_results.items()
            },
        })

        all_passed = all(r.passed for r in oracle_results.values())
        passed_count = sum(1 for r in oracle_results.values() if r.passed)
        total_count = len(oracle_results)

        logger.info(
            f"[{agent_id}] Round {round_num}: "
            f"Oracle checks: {passed_count}/{total_count} passed"
        )

        if all_passed:
            logger.info(
                f"[{agent_id}] All oracle checks passed, accepting patch"
            )
            break

        if round_num < max_oracle_rounds - 1:
            # Format feedback for next round
            oracle_feedback = format_oracle_feedback(
                oracle_results, oracle_strategies
            )
            logger.info(
                f"[{agent_id}] Oracle feedback generated, "
                f"starting round {round_num + 2}"
            )

    # Aggregate trace data
    total_turns = 0
    total_cost = 0.0
    all_messages = []
    errors = []
    for atd in all_trace_datas:
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

    trace_data.patch_produced = bool(final_patch.strip())
    trace_data.patch_content = final_patch

    elapsed = time.time() - start_time
    logger.info(
        f"[{agent_id}] Finished in {elapsed:.1f}s, "
        f"patch={'yes' if final_patch.strip() else 'no'} "
        f"({len(final_patch)} bytes), "
        f"total_turns={total_turns}, total_cost=${total_cost:.4f}, "
        f"rounds={len(oracle_results_history) or 1}"
    )

    return {
        "instance_id": task.instance_id,
        "model_name_or_path": f"kekule-oracle-swarm-{config.model}",
        "model_patch": final_patch,
        "agent_id": agent_id,
        "duration_s": elapsed,
        "num_turns": total_turns,
        "cost_usd": total_cost,
        "swarm_agents": len(all_roles),
        "swarm_design": swarm_design,
        "roles": [r["name"] for r in all_roles],
        "oracle_strategies": [s.name for s in oracle_strategies if s.enabled],
        "oracle_rounds": len(oracle_results_history) or 1,
        "oracle_results": oracle_results_history,
    }


__all__ = ["solve_swe_task"]
