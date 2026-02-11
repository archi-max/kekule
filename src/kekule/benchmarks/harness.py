"""
Main SWE-bench harness orchestrator.

Runs the full experiment:
  1. Select SWE-bench tasks
  2. Setup workspaces (clone repos)
  3. Spawn solver agents in parallel
  4. Collect patches
  5. Run official SWE-bench evaluation
  6. Report results (optionally to LangFuse)
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

import httpx

from .config import HarnessConfig
from .evaluator import (
    prepare_eval_images,
    print_evaluation_summary,
    run_swebench_evaluation,
    write_best_of_n_predictions,
    write_per_agent_predictions,
    write_predictions,
)
from .solver_agent import solve_swe_task, _clone_reference_repo
from .task_selector import SWETask, select_tasks
from .tracing import AgentTraceData, TracingManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


_FUN_NAMES = [
    # Punny / dev-themed
    "ByteNinja", "CaffeineOverflow", "SyntaxSorcerer", "BugWhisperer",
    "NullPointerHero", "GitGoblin", "StackSurfer", "MergeConflictMike",
    "RecursiveRebel", "SegfaultSam", "PatchPirate", "DebugDragon",
    "CompilerCrusader", "LintLord", "RegexRanger", "BinaryBard",
    "HeapHero", "ThreadTamer", "RefactorRaccoon", "DeployDaredevil",
    # Absurd / fun
    "QuantumPickle", "TurboMoose", "NachoCompiler", "CrypticWaffle",
    "ElectricLlama", "SonicPretzel", "LaserPenguin", "GalacticBagel",
    "NeonNarwhal", "PixelPlatypus", "ThunderMuffin", "CosmicBurrito",
    "VelvetThunder", "WarpDriveWombat", "AtomicAvocado", "BlazeKitten",
    # Hacker / gamer vibes
    "xX_CodeSlayer_Xx", "DarkMatterDev", "ZeroDay_Zen", "CyberSamurai",
    "PhantomCoder", "ShadowCompile", "IronPython", "RoguePacket",
    "StealthCommit", "VoidWalker", "ChronoHacker", "NovaByte",
    # Chill / creative
    "CoffeeAndCode", "MidnightMerge", "SunsetScript", "ZenOfPython",
    "LofiLinux", "ChillDebugger", "DreamyDeploy", "MellowMalloc",
    "PeacefulParser", "HappyHashMap", "CozyCompiler", "BreezyCoder",
]


def _generate_fun_username() -> str:
    """Generate a fun, creative username."""
    import random
    base = random.choice(_FUN_NAMES)
    num = random.randint(1, 999)
    return f"{base}{num}"


def register_chatoverflow_agent(
    api_url: str,
    username: str,
) -> str:
    """
    Register an agent on the ChatOverflow API and return its API key.

    Only used when ChatOverflow integration is enabled.
    """
    for attempt in range(5):
        name = _generate_fun_username()
        try:
            resp = httpx.post(
                f"{api_url}/auth/register",
                json={"username": name},
                timeout=10.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"Registered agent: {name} (for {username})")
                return data["api_key"]
            else:
                detail = resp.json().get("detail", resp.text)
                logger.warning(f"Registration attempt {attempt} for {name}: {detail}")
        except Exception as e:
            logger.error(f"Registration error for {name}: {e}")
            if attempt == 4:
                raise

    raise RuntimeError(f"Failed to register agent {username} after 5 attempts")


async def run_iteration(
    iteration: int,
    tasks: list[SWETask],
    config: HarnessConfig,
    tracing: TracingManager,
) -> list[dict]:
    """
    Run one iteration of the experiment.

    Spawns agents_per_problem agents for each task, all in parallel.

    Returns list of result dicts from all agents.
    """
    logger.info(
        f"\n{'='*60}\n"
        f"ITERATION {iteration}\n"
        f"{'='*60}"
    )

    trace = tracing.create_experiment_trace(iteration)

    # Pre-clone reference repos in parallel (one per unique task)
    repo_cache_dir = config.repo_cache_dir
    repo_cache_dir.mkdir(parents=True, exist_ok=True)

    clone_sem = asyncio.Semaphore(3)  # max 3 concurrent clones

    async def _clone_task(task):
        async with clone_sem:
            logger.info(f"Pre-cloning reference repo for {task.instance_id}...")
            ref = await asyncio.to_thread(_clone_reference_repo, task, repo_cache_dir)
            logger.info(f"Reference repo ready: {ref}")
            return task.instance_id, ref

    clone_results = await asyncio.gather(
        *[_clone_task(t) for t in tasks], return_exceptions=True
    )
    ref_repos: dict[str, Path] = {}
    for result in clone_results:
        if isinstance(result, Exception):
            logger.error(f"Clone failed: {result}")
        else:
            ref_repos[result[0]] = result[1]

    # Register agents and create coroutines
    agent_coros = []
    agent_metadata = []  # Track (span, trace_data) for each agent

    for task_idx, task in enumerate(tasks):
        if task.instance_id not in ref_repos:
            logger.warning(
                f"Skipping {task.instance_id} -- reference repo not available"
            )
            continue
        ref_repo_dir = ref_repos[task.instance_id]
        for agent_num in range(config.agents_per_problem):
            agent_id = (
                f"agent-{task.instance_id}-{agent_num}-iter{iteration}"
            )
            workspace_dir = (
                config.workspaces_dir
                / f"iter{iteration}-{task.short_id}-agent{agent_num}"
            )

            # Register on ChatOverflow if enabled
            api_key = ""
            if config.enable_chatoverflow:
                try:
                    api_key = register_chatoverflow_agent(
                        config.chatoverflow_api_url, agent_id
                    )
                except Exception as e:
                    logger.warning(f"ChatOverflow registration failed for {agent_id}: {e}")

            # Create tracing span
            trace_data = AgentTraceData(
                agent_id=agent_id,
                instance_id=task.instance_id,
                agent_num=agent_num,
                iteration=iteration,
                model=config.model,
            )
            span = tracing.create_agent_span(
                trace, agent_id, task.instance_id, agent_num, iteration
            )

            agent_metadata.append((span, trace_data))

            agent_coros.append(
                solve_swe_task(
                    task=task,
                    agent_id=agent_id,
                    workspace_dir=workspace_dir,
                    ref_repo_dir=ref_repo_dir,
                    config=config,
                    trace_data=trace_data,
                    agent_api_key=api_key,
                )
            )

    logger.info(
        f"Spawning {len(agent_coros)} agents "
        f"({config.agents_per_problem} per problem, "
        f"{len(tasks)} problems, "
        f"max_parallel={config.max_parallel})"
    )

    # Run agents with concurrency limit
    semaphore = asyncio.Semaphore(config.max_parallel)

    async def _run_with_limit(coro, idx):
        async with semaphore:
            logger.info(f"Agent slot acquired ({idx+1}/{len(agent_coros)})")
            return await coro

    results = await asyncio.gather(
        *[_run_with_limit(c, i) for i, c in enumerate(agent_coros)],
        return_exceptions=True,
    )

    # Process results and end spans
    processed_results = []
    for i, (result, (span, trace_data)) in enumerate(
        zip(results, agent_metadata)
    ):
        if isinstance(result, Exception):
            logger.error(f"Agent {i} failed with exception: {result}")
            trace_data.error = str(result)
            processed_results.append(
                {
                    "instance_id": trace_data.instance_id,
                    "model_name_or_path": f"kekule-{config.model}",
                    "model_patch": "",
                    "agent_id": trace_data.agent_id,
                    "error": str(result),
                }
            )
        else:
            processed_results.append(result)

        tracing.end_agent_span(span, trace_data)

    # Log experiment summary
    tracing.log_experiment_summary(trace, processed_results)
    tracing.flush()

    return processed_results


async def run_experiment(config: HarnessConfig, skip_eval: bool = False):
    """Run the full experiment across all iterations."""
    config.ensure_dirs()

    logger.info(
        f"Starting SWE-bench experiment:\n"
        f"  Model:             {config.model}\n"
        f"  Problems:          {config.num_problems}\n"
        f"  Agents/problem:    {config.agents_per_problem}\n"
        f"  Iterations:        {config.num_iterations}\n"
        f"  ChatOverflow:      {'enabled' if config.enable_chatoverflow else 'disabled'}\n"
        f"  LangFuse:          {'enabled' if config.langfuse_enabled else 'disabled'}"
    )

    # Initialize tracing
    tracing = TracingManager(config)

    # Select tasks
    tasks = select_tasks(
        task_ids=config.task_ids or None,
        num_problems=config.num_problems,
        repos=config.repos or None,
    )
    logger.info(f"Tasks: {[t.instance_id for t in tasks]}")

    # Run iterations
    all_iteration_results = []
    start = config.start_iteration
    for iteration in range(start, start + config.num_iterations):
        results = await run_iteration(iteration, tasks, config, tracing)
        all_iteration_results.append(results)

        # Write predictions for this iteration
        iter_dir = config.results_dir / f"iteration_{iteration}"
        write_predictions(results, iter_dir, f"iter{iteration}")
        write_per_agent_predictions(
            results, iter_dir, config.agents_per_problem
        )
        write_best_of_n_predictions(results, iter_dir)

        # Save raw results as JSON
        with open(iter_dir / "raw_results.json", "w") as f:
            json.dump(results, f, indent=2, default=str)

    if skip_eval:
        logger.info("Skipping SWE-bench evaluation (--skip-eval)")
    else:
        # Pre-build Docker images for all tasks
        logger.info("\n" + "=" * 60)
        logger.info("PREPARING SWE-BENCH DOCKER IMAGES")
        logger.info("=" * 60)

        task_instance_ids = [t.instance_id for t in tasks]
        try:
            prepare_eval_images(task_instance_ids, max_workers=1)
        except Exception as e:
            logger.error(f"Image preparation failed: {e}")
            logger.info("Continuing without evaluation...")
            skip_eval = True

    if not skip_eval:
        # Run official SWE-bench evaluation on all iterations
        logger.info("\n" + "=" * 60)
        logger.info("RUNNING OFFICIAL SWE-BENCH EVALUATION")
        logger.info("=" * 60)

        for iteration, results in enumerate(all_iteration_results):
            iter_dir = config.results_dir / f"iteration_{iteration}"

            # Evaluate best-of-N predictions
            best_predictions = iter_dir / "predictions_best_of_n.jsonl"
            if best_predictions.exists():
                eval_results = run_swebench_evaluation(
                    best_predictions,
                    run_id=f"kekule_iter{iteration}_best",
                    max_workers=min(4, config.num_problems),
                )
                print_evaluation_summary(eval_results)

                # Log to LangFuse if enabled
                if tracing.enabled:
                    trace = tracing.create_experiment_trace(
                        iteration + 100  # Offset to distinguish eval traces
                    )
                    tracing.log_experiment_summary(trace, [
                        {"passed": eval_results.get("passed", 0) > 0, **r}
                        for r in results
                    ])

            # Evaluate per-agent predictions
            for agent_pred in iter_dir.glob("predictions_agent*.jsonl"):
                agent_label = agent_pred.stem.replace("predictions_", "")
                eval_results = run_swebench_evaluation(
                    agent_pred,
                    run_id=f"kekule_iter{iteration}_{agent_label}",
                    max_workers=min(4, config.num_problems),
                )
                print_evaluation_summary(eval_results)

    tracing.flush()
    tracing.shutdown()

    # Print final summary
    print("\n" + "=" * 60)
    print("EXPERIMENT COMPLETE")
    print("=" * 60)
    print(f"Results saved to: {config.results_dir}")
    if config.langfuse_enabled:
        print(f"Check LangFuse at: {config.langfuse_base_url}")
    print("=" * 60)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SWE-bench validation loop with Claude Agent SDK",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model to use (e.g., claude-opus-4-5, claude-sonnet-4-5)",
    )
    parser.add_argument(
        "--problems",
        type=int,
        default=None,
        help="Number of SWE-bench problems to solve (default: 3)",
    )
    parser.add_argument(
        "--agents-per-problem",
        type=int,
        default=None,
        help="Number of agents per problem (default: 3)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Number of experiment iterations (default: 3)",
    )
    parser.add_argument(
        "--task-ids",
        nargs="+",
        default=None,
        help="Specific SWE-bench instance IDs to use",
    )
    parser.add_argument(
        "--repos",
        nargs="+",
        default=None,
        help="Select all tasks from these repos (e.g., psf/requests pytest-dev/pytest)",
    )
    parser.add_argument(
        "--chatoverflow-url",
        type=str,
        default=None,
        help="ChatOverflow API URL (default: https://www.chatoverflow.dev)",
    )
    parser.add_argument(
        "--enable-chatoverflow",
        action="store_true",
        help="Enable ChatOverflow Q&A forum integration for agents",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=None,
        help="Max agent turns per task (default: 100)",
    )
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=None,
        help="Max agents running in parallel (default: 6)",
    )
    parser.add_argument(
        "--start-iteration",
        type=int,
        default=None,
        help="Starting iteration number (default: 0, use 3 to continue after 0-2)",
    )
    parser.add_argument(
        "--skip-eval",
        action="store_true",
        help="Skip SWE-bench evaluation (just run agents and collect patches)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print configuration and exit without running",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    config = HarnessConfig.from_args(args)

    if args.dry_run:
        print("DRY RUN -- Configuration:")
        print(f"  Model:             {config.model}")
        print(f"  Problems:          {config.num_problems}")
        print(f"  Agents/problem:    {config.agents_per_problem}")
        print(f"  Iterations:        {config.num_iterations}")
        print(f"  Max turns:         {config.max_agent_turns}")
        print(f"  Task IDs:          {config.task_ids or 'auto-select'}")
        print(f"  ChatOverflow:      {'enabled' if config.enable_chatoverflow else 'disabled'}")
        print(f"  ChatOverflow URL:  {config.chatoverflow_api_url}")
        print(f"  LangFuse:          {'enabled' if config.langfuse_enabled else 'disabled'}")
        print(f"  Results dir:       {config.results_dir}")
        print(f"  Workspaces dir:    {config.workspaces_dir}")
        claude_env = config.get_claude_env()
        print(f"  Claude API base:   {claude_env.get('ANTHROPIC_BASE_URL', 'default')}")
        sys.exit(0)

    asyncio.run(run_experiment(config, skip_eval=args.skip_eval))


if __name__ == "__main__":
    main()
