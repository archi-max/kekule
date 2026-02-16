"""
Self-Improving Harness -- outer loop orchestrator for the oracle swarm.

Runs multiple epochs of SWE-bench solving with cross-epoch learning:
  1. Split tasks into train/test (deterministic, same split every epoch)
  2. Run oracle_swarm solver on all tasks with current lessons + strategies
  3. Evaluate patches with SWE-bench Docker evaluation
  4. Run waypoint coordinator to analyze results and produce improvements
  5. Apply improvements for the next epoch
  6. Track scores and prompt evolution over time
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

from .config import HarnessConfig
from .evaluator import (
    prepare_eval_images,
    print_evaluation_summary,
    run_swebench_evaluation,
    write_best_of_n_predictions,
    write_per_agent_predictions,
    write_predictions,
)
from .oracle_bridge import (
    DEFAULT_ORACLE_STRATEGIES,
    OracleStrategy,
    apply_oracle_adjustments,
)
from .solver_agent import _clone_reference_repo
from .task_selector import SWETask, select_tasks
from .task_splitter import split_tasks
from .tracing import AgentTraceData, TracingManager
from .prompt_config import PromptConfig
from .failure_analyst import (
    analyze_all_failures,
    diagnoses_to_json,
    format_diagnoses_for_coordinator,
)
from .waypoint_coordinator import (
    CompositionConfig,
    CoordinatorOutput,
    analyze_epoch,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _load_solver_fn(solver_name: str):
    """Load a solver function by name, with self-improving wrapper if needed."""
    from .harness import load_solver
    return load_solver(solver_name)


def _extract_agent_log_summary(
    trace_data: AgentTraceData,
    max_chars: int = 4000,
) -> str:
    """Extract a text summary of agent reasoning from trace messages.

    Pulls out the agent's text blocks (its thinking/reasoning) and tool
    call names to create a readable log of what the agent did and why.
    This is what the waypoint coordinator sees for train tasks.

    Args:
        trace_data: The agent's accumulated trace data.
        max_chars: Maximum summary length.

    Returns:
        A string summary of the agent's key decisions.
    """
    lines: list[str] = []

    if trace_data.error:
        lines.append(f"[ERROR] {trace_data.error}")

    for msg in trace_data.messages:
        msg_type = msg.get("type")

        if msg_type == "assistant":
            for block in msg.get("content", []):
                if block.get("type") == "text":
                    text = block["text"].strip()
                    if text:
                        # Truncate very long text blocks
                        if len(text) > 500:
                            text = text[:500] + "..."
                        lines.append(f"[thought] {text}")
                elif block.get("type") == "tool_use":
                    tool_name = block.get("name", "?")
                    tool_input = block.get("input", {})
                    # Summarize the tool call
                    if tool_name in ("Read", "Grep", "Glob"):
                        target = ""
                        if isinstance(tool_input, dict):
                            target = (
                                tool_input.get("file_path", "")
                                or tool_input.get("pattern", "")
                                or tool_input.get("path", "")
                            )
                        lines.append(f"[tool] {tool_name}: {target}")
                    elif tool_name in ("Edit", "Write"):
                        fp = tool_input.get("file_path", "") if isinstance(tool_input, dict) else ""
                        lines.append(f"[tool] {tool_name}: {fp}")
                    elif tool_name == "Bash":
                        cmd = tool_input.get("command", "")[:120] if isinstance(tool_input, dict) else ""
                        lines.append(f"[tool] Bash: {cmd}")
                    else:
                        lines.append(f"[tool] {tool_name}")

        elif msg_type == "tool_result":
            if msg.get("is_error"):
                content = str(msg.get("content", ""))[:200]
                lines.append(f"[tool_error] {content}")

    summary = "\n".join(lines)

    # Truncate to max_chars
    if len(summary) > max_chars:
        summary = summary[:max_chars] + "\n... (truncated)"

    return summary


async def _run_epoch_tasks(
    epoch: int,
    tasks: list[SWETask],
    config: HarnessConfig,
    tracing: TracingManager,
    lessons_text: str,
    oracle_strategies: list[OracleStrategy],
    composition: CompositionConfig,
    solver_name: str = "oracle_swarm",
) -> list[dict]:
    """Run all tasks for one epoch using the configured solver.

    Returns list of result dicts from all agents.
    """
    solve_swe_task = _load_solver_fn(solver_name)

    logger.info(
        f"\n{'='*60}\n"
        f"EPOCH {epoch} — Running {len(tasks)} tasks\n"
        f"{'='*60}"
    )

    trace = tracing.create_experiment_trace(epoch)

    # Pre-clone reference repos
    repo_cache_dir = config.repo_cache_dir
    repo_cache_dir.mkdir(parents=True, exist_ok=True)

    clone_sem = asyncio.Semaphore(3)

    async def _clone_task(task):
        async with clone_sem:
            logger.info(f"Pre-cloning reference repo for {task.instance_id}...")
            ref = await asyncio.to_thread(
                _clone_reference_repo, task, repo_cache_dir
            )
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

    # Create coroutines for all tasks
    agent_coros = []
    agent_metadata = []

    for task in tasks:
        if task.instance_id not in ref_repos:
            logger.warning(
                f"Skipping {task.instance_id} -- reference repo not available"
            )
            continue

        ref_repo_dir = ref_repos[task.instance_id]
        agent_id = f"epoch{epoch}-{task.instance_id}"
        workspace_dir = (
            config.workspaces_dir / f"epoch{epoch}-{task.short_id}"
        )

        trace_data = AgentTraceData(
            agent_id=agent_id,
            instance_id=task.instance_id,
            agent_num=0,
            iteration=epoch,
            model=config.model,
        )
        span = tracing.create_agent_span(
            trace, agent_id, task.instance_id, 0, epoch
        )

        # Register on ChatOverflow if enabled
        agent_api_key = ""
        if config.enable_chatoverflow:
            try:
                from .harness import register_chatoverflow_agent
                agent_api_key = register_chatoverflow_agent(
                    config.chatoverflow_api_url, agent_id
                )
            except Exception as e:
                logger.warning(
                    f"ChatOverflow registration failed for {agent_id}: {e}"
                )

        agent_metadata.append((span, trace_data))

        # Build kwargs — oracle_swarm accepts extra params,
        # other solvers (perturbation_swarm, default) use the base signature
        solver_kwargs: dict = {
            "task": task,
            "agent_id": agent_id,
            "workspace_dir": workspace_dir,
            "ref_repo_dir": ref_repo_dir,
            "config": config,
            "trace_data": trace_data,
            "agent_api_key": agent_api_key,
        }
        if solver_name == "oracle_swarm":
            solver_kwargs["lessons_text"] = lessons_text
            solver_kwargs["oracle_strategies"] = oracle_strategies
            solver_kwargs["max_oracle_rounds"] = composition.num_oracle_rounds

        agent_coros.append(solve_swe_task(**solver_kwargs))

    logger.info(
        f"Spawning {len(agent_coros)} oracle swarm solvers "
        f"(max_parallel={config.max_parallel})"
    )

    # Run with concurrency limit
    semaphore = asyncio.Semaphore(config.max_parallel)

    async def _run_with_limit(coro, idx):
        async with semaphore:
            logger.info(f"Task slot acquired ({idx+1}/{len(agent_coros)})")
            return await coro

    results = await asyncio.gather(
        *[_run_with_limit(c, i) for i, c in enumerate(agent_coros)],
        return_exceptions=True,
    )

    # Process results — attach agent log summaries for coordinator analysis
    processed_results = []
    for i, (result, (span, trace_data)) in enumerate(
        zip(results, agent_metadata)
    ):
        if isinstance(result, BaseException):
            logger.error(f"Task {i} failed with exception: {result}")
            trace_data.error = str(result)
            processed_results.append({
                "instance_id": trace_data.instance_id,
                "model_name_or_path": f"kekule-oracle-swarm-{config.model}",
                "model_patch": "",
                "agent_id": trace_data.agent_id,
                "error": str(result),
            })
        else:
            # Attach agent conversation summary to result for coordinator
            result["agent_logs"] = _extract_agent_log_summary(trace_data)
            processed_results.append(result)

        tracing.end_agent_span(span, trace_data)

    tracing.log_experiment_summary(trace, processed_results)
    tracing.flush()

    return processed_results


def _evaluate_results(
    results: list[dict],
    epoch: int,
    config: HarnessConfig,
    skip_eval: bool,
    experiment_dir: Path | None = None,
) -> dict:
    """Run SWE-bench evaluation and return eval results."""
    base_dir = experiment_dir or config.results_dir
    iter_dir = base_dir / f"epoch_{epoch}"
    write_predictions(results, iter_dir, f"epoch{epoch}")
    write_per_agent_predictions(results, iter_dir, 1)
    write_best_of_n_predictions(results, iter_dir)

    # Save raw results
    with open(iter_dir / "raw_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)

    if skip_eval:
        logger.info("Skipping SWE-bench evaluation (--skip-eval)")
        return {}

    task_ids = list({r["instance_id"] for r in results})
    try:
        prepare_eval_images(task_ids, max_workers=1)
    except Exception as e:
        logger.error(f"Image preparation failed: {e}")
        return {}

    best_predictions = iter_dir / "predictions_best_of_n.jsonl"
    if best_predictions.exists():
        eval_results = run_swebench_evaluation(
            best_predictions,
            run_id=f"kekule_epoch{epoch}_best",
            max_workers=min(4, len(task_ids)),
        )
        print_evaluation_summary(eval_results)
        return eval_results

    return {}


def _merge_eval_into_results(
    results: list[dict],
    eval_results: dict,
) -> list[dict]:
    """Merge evaluation results into result dicts.

    Includes the full test status breakdown (FAIL_TO_PASS, PASS_TO_PASS, etc.)
    so the coordinator can see exactly which tests passed/failed for train tasks.
    The golden patch is intentionally NOT included — that would be cheating.
    """
    instances = eval_results.get("instances", {})
    for r in results:
        iid = r["instance_id"]
        if iid in instances:
            status = instances[iid]
            r["resolved"] = status.get("resolved", False)
            r["patch_applied"] = status.get("patch_successfully_applied", False)
            # Include full test breakdown for coordinator analysis
            tests_status = status.get("tests_status", {})
            if tests_status:
                f2p = tests_status.get("FAIL_TO_PASS", {})
                p2p = tests_status.get("PASS_TO_PASS", {})
                r["eval_tests"] = {
                    "fail_to_pass_fixed": f2p.get("success", []),
                    "fail_to_pass_still_failing": f2p.get("failure", []),
                    "pass_to_pass_ok": len(p2p.get("success", [])),
                    "pass_to_pass_regressed": p2p.get("failure", []),
                }
        else:
            r["resolved"] = False
    return results


async def run_self_improving(
    config: HarnessConfig,
    num_epochs: int = 3,
    train_ratio: float = 0.7,
    skip_eval: bool = False,
    prompts_dir: str | Path | None = None,
    solver_name: str = "oracle_swarm",
    train_ids: list[str] | None = None,
    test_ids: list[str] | None = None,
):
    """Run the self-improving loop across multiple epochs.

    Args:
        config: Harness configuration.
        num_epochs: Number of epochs to run.
        train_ratio: Fraction of tasks for training (used if train_ids/test_ids not set).
        skip_eval: Skip SWE-bench Docker evaluation.
        prompts_dir: Directory with prompt override files (.md/.txt).
        solver_name: Solver module name (e.g., "perturbation_swarm", "oracle_swarm").
        train_ids: Explicit train task IDs. Overrides train_ratio splitting.
        test_ids: Explicit test task IDs. Overrides train_ratio splitting.
    """
    config.ensure_dirs()
    # Use experiment name as subdirectory so runs don't collide
    if config.experiment_name:
        experiment_dir = config.results_dir / config.experiment_name
    else:
        experiment_dir = config.results_dir
    experiment_dir.mkdir(parents=True, exist_ok=True)

    # Initialize prompt configuration
    if prompts_dir:
        prompt_config = PromptConfig.from_dir(prompts_dir)
        logger.info(f"Loading prompt overrides from: {prompts_dir}")
    else:
        prompt_config = PromptConfig()

    # Save initial prompts for reference (users can edit these and reload)
    initial_prompts_dir = experiment_dir / "prompts"
    if not initial_prompts_dir.exists():
        prompt_config.save_to_dir(initial_prompts_dir)
        logger.info(
            f"Saved initial prompts to {initial_prompts_dir}/ — "
            f"edit these files and pass --prompts-dir to override"
        )

    tracing = TracingManager(config)

    # Select tasks -- use explicit train/test IDs or auto-split
    if train_ids and test_ids:
        # Explicit train/test split
        all_ids = list(dict.fromkeys(train_ids + test_ids))  # deduplicated
        all_tasks = select_tasks(
            task_ids=all_ids,
            num_problems=len(all_ids),
            dataset=config.dataset,
        )
        task_map = {t.instance_id: t for t in all_tasks}
        train_tasks = [task_map[tid] for tid in train_ids if tid in task_map]
        test_tasks = [task_map[tid] for tid in test_ids if tid in task_map]
    else:
        all_tasks = select_tasks(
            task_ids=config.task_ids or None,
            num_problems=config.num_problems,
            repos=config.repos or None,
            task_file=config.task_file or None,
            dataset=config.dataset,
        )
        train_tasks, test_tasks = split_tasks(all_tasks, train_ratio)

    all_tasks_combined = train_tasks + test_tasks

    logger.info(
        f"Task split: {len(train_tasks)} train, {len(test_tasks)} test "
        f"(solver={solver_name})"
    )
    logger.info(f"Train: {[t.instance_id for t in train_tasks]}")
    logger.info(f"Test:  {[t.instance_id for t in test_tasks]}")

    # Save split info
    split_info = {
        "train_ids": [t.instance_id for t in train_tasks],
        "test_ids": [t.instance_id for t in test_tasks],
        "train_ratio": train_ratio,
    }
    with open(experiment_dir / "split.json", "w") as f:
        json.dump(split_info, f, indent=2)

    # Initialize mutable state — restore from previous epochs if resuming
    lessons_text = ""
    oracle_strategies = list(DEFAULT_ORACLE_STRATEGIES)
    composition = CompositionConfig()
    scores: list[dict] = []
    start_epoch = getattr(config, "start_iteration", 0)

    if start_epoch > 0:
        logger.info(f"Resuming from epoch {start_epoch}, loading prior state...")
        # Rebuild lessons from all prior coordinator outputs
        for prev_epoch in range(start_epoch):
            coord_file = experiment_dir / f"epoch_{prev_epoch}" / "coordinator_output.json"
            if coord_file.exists():
                try:
                    coord_data = json.loads(coord_file.read_text())
                    prev_lessons = coord_data.get("lessons_text", "")
                    if prev_lessons:
                        lessons_text += f"\n\n### Epoch {prev_epoch} Lessons\n{prev_lessons}"
                        logger.info(f"  Loaded {len(prev_lessons)} chars of lessons from epoch {prev_epoch}")

                    # Restore oracle adjustments
                    prev_adj = coord_data.get("oracle_adjustments", {})
                    if prev_adj:
                        oracle_strategies = apply_oracle_adjustments(oracle_strategies, prev_adj)
                        logger.info(f"  Applied oracle adjustments from epoch {prev_epoch}")

                    # Restore composition
                    prev_comp = coord_data.get("composition", {})
                    if prev_comp:
                        if "num_coding_agents" in prev_comp:
                            composition.num_coding_agents = prev_comp["num_coding_agents"]
                        if "num_oracle_rounds" in prev_comp:
                            composition.num_oracle_rounds = prev_comp["num_oracle_rounds"]
                        if "oracle_parallelism" in prev_comp:
                            composition.oracle_parallelism = prev_comp["oracle_parallelism"]
                        if "planner_guidance" in prev_comp:
                            composition.planner_guidance = prev_comp["planner_guidance"]
                except Exception as e:
                    logger.warning(f"  Failed to load epoch {prev_epoch} state: {e}")

        # Load existing scores
        scores_file = experiment_dir / "scores.json"
        if scores_file.exists():
            try:
                scores = json.loads(scores_file.read_text())
                scores = [s for s in scores if s.get("epoch", 0) < start_epoch]
                logger.info(f"  Loaded {len(scores)} prior epoch scores")
            except Exception:
                pass

        logger.info(
            f"Resumed state: {len(lessons_text)} chars lessons, "
            f"composition=agents:{composition.num_coding_agents}/rounds:{composition.num_oracle_rounds}"
        )

    train_ids = {t.instance_id for t in train_tasks}
    test_ids = {t.instance_id for t in test_tasks}

    for epoch in range(start_epoch, start_epoch + num_epochs):
        epoch_start = time.time()
        logger.info(
            f"\n{'#'*60}\n"
            f"# EPOCH {epoch + 1}/{num_epochs}\n"
            f"{'#'*60}"
        )

        # Save full prompt snapshot (all prompts + config state)
        snapshot_dir = experiment_dir / "prompt_snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        prompt_config.save_snapshot(
            snapshot_dir / f"epoch_{epoch}_prompts.json"
        )
        with open(snapshot_dir / f"epoch_{epoch}_config.json", "w") as f:
            json.dump({
                "lessons_text": lessons_text,
                "oracle_strategies": [
                    s.model_dump() for s in oracle_strategies
                ],
                "composition": {
                    "num_coding_agents": composition.num_coding_agents,
                    "num_oracle_rounds": composition.num_oracle_rounds,
                    "oracle_parallelism": composition.oracle_parallelism,
                    "planner_guidance": composition.planner_guidance,
                },
                "prompt_overrides": list(prompt_config.overrides.keys()),
            }, f, indent=2)

        # Run all tasks
        results = await _run_epoch_tasks(
            epoch=epoch,
            tasks=all_tasks_combined,
            config=config,
            tracing=tracing,
            lessons_text=lessons_text,
            oracle_strategies=oracle_strategies,
            composition=composition,
            solver_name=solver_name,
        )

        # Evaluate
        eval_results = _evaluate_results(results, epoch, config, skip_eval, experiment_dir)
        results = _merge_eval_into_results(results, eval_results)

        # Split results into train/test
        train_results = [r for r in results if r["instance_id"] in train_ids]
        test_results = [r for r in results if r["instance_id"] in test_ids]

        # Collect oracle results for train tasks
        train_oracle_results = {}
        for r in train_results:
            if r.get("oracle_results"):
                train_oracle_results[r["instance_id"]] = r["oracle_results"]

        # Compute scores
        train_passed = sum(1 for r in train_results if r.get("resolved"))
        test_passed = sum(1 for r in test_results if r.get("resolved"))
        train_score = train_passed / len(train_results) if train_results else 0
        test_score = test_passed / len(test_results) if test_results else 0

        epoch_elapsed = time.time() - epoch_start
        epoch_cost = sum(r.get("cost_usd", 0) for r in results)

        score_entry = {
            "epoch": epoch,
            "train_score": train_score,
            "test_score": test_score,
            "train_passed": train_passed,
            "train_total": len(train_results),
            "test_passed": test_passed,
            "test_total": len(test_results),
            "total_cost_usd": epoch_cost,
            "duration_s": epoch_elapsed,
        }
        scores.append(score_entry)

        logger.info(
            f"\nEpoch {epoch} results: "
            f"train={train_passed}/{len(train_results)} ({train_score:.1%}), "
            f"test={test_passed}/{len(test_results)} ({test_score:.1%}), "
            f"cost=${epoch_cost:.2f}"
        )

        # Save scores
        with open(experiment_dir / "scores.json", "w") as f:
            json.dump(scores, f, indent=2)

        # Run waypoint coordinator (except after the last epoch)
        if epoch < num_epochs - 1:
            # ── Phase: Failure Analysis ────────────────────────────
            # Per-task diagnosis of WHY each failed train task failed
            failed_train = [
                r for r in train_results if not r.get("resolved", False)
            ]

            diagnoses = []
            if failed_train:
                logger.info(
                    f"\n{'='*60}\n"
                    f"FAILURE ANALYSIS — {len(failed_train)} failed train tasks\n"
                    f"{'='*60}"
                )

                task_map = {t.instance_id: t for t in all_tasks_combined}
                diagnoses = await analyze_all_failures(
                    failed_results=failed_train,
                    tasks_by_id=task_map,
                    model=getattr(config, "oracle_model", "claude-sonnet-4-5"),
                    max_parallel=min(5, config.max_parallel),
                )

                # Save diagnoses
                epoch_dir = experiment_dir / f"epoch_{epoch}"
                epoch_dir.mkdir(parents=True, exist_ok=True)
                with open(epoch_dir / "failure_diagnoses.json", "w") as f:
                    json.dump(diagnoses_to_json(diagnoses), f, indent=2)

                for d in diagnoses:
                    logger.info(
                        f"[diagnosis:{d.instance_id}] "
                        f"root_cause={d.root_cause[:80]}... "
                        f"missed={len(d.what_swarm_missed)} things, "
                        f"behaviors={len(d.behaviors_to_fix)}"
                    )

            # Format diagnoses as context for the coordinator
            diagnosis_context = format_diagnoses_for_coordinator(diagnoses)

            # ── Phase: Waypoint Coordinator ────────────────────────
            logger.info(
                f"\n{'='*60}\n"
                f"WAYPOINT COORDINATOR — Analyzing epoch {epoch}\n"
                f"{'='*60}"
            )

            # Prepare test results with NO logs (just pass/fail)
            test_results_sanitized = [
                {
                    "instance_id": r["instance_id"],
                    "resolved": r.get("resolved", False),
                }
                for r in test_results
            ]

            # Inject failure diagnoses into train results for the coordinator
            if diagnosis_context:
                for r in train_results:
                    if not r.get("resolved", False):
                        # Replace raw agent_logs with structured diagnosis
                        matching = [
                            d for d in diagnoses
                            if d.instance_id == r["instance_id"]
                        ]
                        if matching:
                            d = matching[0]
                            r["failure_diagnosis"] = {
                                "root_cause": d.root_cause,
                                "what_swarm_missed": d.what_swarm_missed,
                                "behaviors_to_fix": d.behaviors_to_fix,
                                "test_analysis": d.test_analysis,
                                "suggestion": d.suggestion,
                            }

            coordinator_output = await analyze_epoch(
                train_results=train_results,
                test_results=test_results_sanitized,
                train_oracle_results=train_oracle_results,
                previous_lessons=lessons_text,
                current_strategies=oracle_strategies,
                current_composition=composition,
                epoch_num=epoch,
                model=getattr(config, "coordinator_model", "claude-opus-4-5"),
            )

            # Apply adjustments
            if coordinator_output.lessons_text:
                lessons_text += (
                    f"\n\n### Epoch {epoch} Lessons\n"
                    f"{coordinator_output.lessons_text}"
                )
                logger.info(
                    f"Added {len(coordinator_output.lessons_text)} chars of lessons"
                )

            if coordinator_output.oracle_adjustments:
                oracle_strategies = apply_oracle_adjustments(
                    oracle_strategies, coordinator_output.oracle_adjustments
                )
                logger.info(
                    f"Applied oracle adjustments: "
                    f"{list(coordinator_output.oracle_adjustments.keys())}"
                )

            composition = coordinator_output.composition
            logger.info(
                f"Composition: agents={composition.num_coding_agents}, "
                f"rounds={composition.num_oracle_rounds}, "
                f"parallelism={composition.oracle_parallelism}"
            )

            # Save coordinator output
            epoch_dir = experiment_dir / f"epoch_{epoch}"
            epoch_dir.mkdir(parents=True, exist_ok=True)
            with open(epoch_dir / "coordinator_output.json", "w") as f:
                json.dump({
                    "lessons_text": coordinator_output.lessons_text,
                    "oracle_adjustments": coordinator_output.oracle_adjustments,
                    "composition": {
                        "num_coding_agents": composition.num_coding_agents,
                        "num_oracle_rounds": composition.num_oracle_rounds,
                        "oracle_parallelism": composition.oracle_parallelism,
                        "planner_guidance": composition.planner_guidance,
                    },
                    "analysis": coordinator_output.analysis,
                    "train_score": coordinator_output.train_score,
                    "test_score": coordinator_output.test_score,
                }, f, indent=2)

    # Save final accumulated lessons
    with open(experiment_dir / "lessons.md", "w") as f:
        f.write(f"# Accumulated Lessons\n\n{lessons_text}\n")

    tracing.flush()
    tracing.shutdown()

    # Print final summary
    print("\n" + "=" * 60)
    print("SELF-IMPROVING EXPERIMENT COMPLETE")
    print("=" * 60)
    print(f"Results saved to: {experiment_dir}")
    print(f"\nScore progression:")
    for s in scores:
        print(
            f"  Epoch {s['epoch']}: "
            f"train={s['train_passed']}/{s['train_total']} "
            f"({s['train_score']:.1%}), "
            f"test={s['test_passed']}/{s['test_total']} "
            f"({s['test_score']:.1%}), "
            f"cost=${s['total_cost_usd']:.2f}"
        )
    print("=" * 60)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Self-improving oracle swarm for SWE-bench",
    )
    parser.add_argument(
        "--experiment-name", type=str, default=None,
        help="Label for this experiment run",
    )
    parser.add_argument(
        "--dataset", type=str, default=None, choices=["lite", "full"],
        help="SWE-bench dataset: 'lite' or 'full'",
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="Model for swarm agents",
    )
    parser.add_argument(
        "--solver", type=str, default="oracle_swarm",
        help="Solver module: oracle_swarm, perturbation_swarm, default",
    )
    parser.add_argument(
        "--coordinator-model", type=str, default="claude-opus-4-5",
        help="Model for the waypoint coordinator",
    )
    parser.add_argument(
        "--epochs", type=int, default=3,
        help="Number of self-improving epochs",
    )
    parser.add_argument(
        "--start-epoch", type=int, default=0,
        help="Resume from this epoch (loads lessons/config from prior epochs)",
    )
    parser.add_argument(
        "--train-ratio", type=float, default=0.7,
        help="Fraction of tasks for training (0.0-1.0)",
    )
    parser.add_argument(
        "--train-ids", nargs="+", default=None,
        help="Explicit train task IDs (overrides --train-ratio)",
    )
    parser.add_argument(
        "--test-ids", nargs="+", default=None,
        help="Explicit test task IDs (overrides --train-ratio)",
    )
    parser.add_argument(
        "--problems", type=int, default=None,
        help="Number of SWE-bench problems (for auto-split mode)",
    )
    parser.add_argument(
        "--task-ids", nargs="+", default=None,
        help="Specific SWE-bench instance IDs (for auto-split mode)",
    )
    parser.add_argument(
        "--task-file", type=str, default=None,
        help="JSON file with task_ids array",
    )
    parser.add_argument(
        "--repos", nargs="+", default=None,
        help="Select tasks from these repos",
    )
    parser.add_argument(
        "--max-parallel", type=int, default=None,
        help="Max agents running in parallel",
    )
    parser.add_argument(
        "--max-turns", type=int, default=None,
        help="Max agent turns per task",
    )
    parser.add_argument(
        "--enable-chatoverflow", action="store_true",
        help="Enable ChatOverflow Q&A forum integration",
    )
    parser.add_argument(
        "--chatoverflow-url", type=str, default=None,
        help="ChatOverflow API URL",
    )
    parser.add_argument(
        "--prompts-dir", type=str, default=None,
        help=(
            "Directory with prompt override files (.md/.txt). "
            "Each file overrides one prompt by key (e.g., swarm_protocol.md). "
            "On first run, default prompts are saved to results/{exp}/prompts/ "
            "for easy editing."
        ),
    )
    parser.add_argument(
        "--skip-eval", action="store_true",
        help="Skip SWE-bench Docker evaluation",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print configuration and exit",
    )
    parser.add_argument(
        "--export-prompts", type=str, default=None,
        help="Export all default prompts to a directory and exit",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    config = HarnessConfig.from_args(args)

    # Export prompts mode
    if args.export_prompts:
        prompt_config = PromptConfig()
        export_dir = Path(args.export_prompts)
        prompt_config.save_to_dir(export_dir)
        print(f"Exported {len(prompt_config.list_keys())} prompts to {export_dir}/")
        print("Edit these files and pass --prompts-dir to use them.")
        sys.exit(0)

    # Set start_iteration for resume support
    config.start_iteration = args.start_epoch

    if args.dry_run:
        print("DRY RUN — Self-Improving Configuration:")
        print(f"  Experiment:        {config.experiment_name or '(unnamed)'}")
        print(f"  Solver:            {args.solver}")
        print(f"  Model:             {config.model}")
        print(f"  Coordinator:       {args.coordinator_model}")
        print(f"  Start epoch:       {args.start_epoch}")
        print(f"  Epochs:            {args.epochs}")
        print(f"  Train IDs:         {args.train_ids or f'auto ({args.train_ratio})'}")
        print(f"  Test IDs:          {args.test_ids or f'auto ({1-args.train_ratio})'}")
        print(f"  Problems:          {config.num_problems}")
        print(f"  Max parallel:      {config.max_parallel}")
        print(f"  ChatOverflow:      {'enabled' if config.enable_chatoverflow else 'disabled'}")
        print(f"  LangFuse:          {'enabled' if config.langfuse_enabled else 'disabled'}")
        print(f"  Prompts dir:       {args.prompts_dir or '(defaults)'}")
        print(f"  Results dir:       {config.results_dir}")
        sys.exit(0)

    asyncio.run(
        run_self_improving(
            config=config,
            num_epochs=args.epochs,
            train_ratio=args.train_ratio,
            skip_eval=args.skip_eval,
            prompts_dir=args.prompts_dir,
            solver_name=args.solver,
            train_ids=args.train_ids,
            test_ids=args.test_ids,
        )
    )


if __name__ == "__main__":
    main()
