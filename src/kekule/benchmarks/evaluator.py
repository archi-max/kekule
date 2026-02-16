"""
Evaluation module -- uses the official SWE-bench harness to evaluate patches.

Workflow:
  1. Collect patches from all agents into a predictions JSONL file
  2. Build Docker images
  3. Run `swebench.harness.run_evaluation` (Docker-based, same as leaderboard)
  4. Parse results and report pass/fail per agent per instance
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def write_predictions(
    results: list[dict],
    output_path: Path,
    run_label: str = "kekule",
) -> Path:
    """
    Write agent results into the SWE-bench predictions JSONL format.

    Each line: {"instance_id": "...", "model_name_or_path": "...", "model_patch": "..."}

    Args:
        results: List of dicts from solve_swe_task()
        output_path: Directory to write the file
        run_label: Label for this run (used in filename)

    Returns:
        Path to the written predictions file
    """
    output_path.mkdir(parents=True, exist_ok=True)
    predictions_file = output_path / f"predictions_{run_label}.jsonl"

    with open(predictions_file, "w") as f:
        for result in results:
            if not result.get("model_patch"):
                logger.warning(
                    f"No patch for {result['instance_id']} "
                    f"(agent={result.get('agent_id')}), writing empty patch"
                )

            prediction = {
                "instance_id": result["instance_id"],
                "model_name_or_path": result.get(
                    "model_name_or_path", "kekule"
                ),
                "model_patch": result.get("model_patch", ""),
            }
            f.write(json.dumps(prediction) + "\n")

    logger.info(
        f"Wrote {len(results)} predictions to {predictions_file}"
    )
    return predictions_file


def write_per_agent_predictions(
    all_results: list[dict],
    output_path: Path,
    agents_per_problem: int,
) -> list[Path]:
    """
    Write separate prediction files for each agent index (agent0, agent1, agent2).

    This allows evaluating each agent's patches independently to compare
    individual vs collaborative performance.

    Returns list of prediction file paths.
    """
    # Group by agent number
    agent_groups: dict[int, list[dict]] = {}
    for result in all_results:
        agent_id = result.get("agent_id", "")
        # Extract agent number from ID like "agent-django__django-16379-1-iter0"
        parts = agent_id.rsplit("-", 2)  # [..., agent_num, "iter0"]
        try:
            agent_num = int(parts[-2]) if len(parts) >= 2 else 0
        except (ValueError, IndexError):
            agent_num = 0

        agent_groups.setdefault(agent_num, []).append(result)

    paths = []
    for agent_num, results in sorted(agent_groups.items()):
        p = write_predictions(results, output_path, f"agent{agent_num}")
        paths.append(p)

    return paths


def pick_best_patch(results_for_instance: list[dict]) -> dict:
    """
    From multiple agent results for the same instance, pick the best patch.

    Heuristic: prefer non-empty patches, then longest (more complete fix).
    """
    non_empty = [r for r in results_for_instance if r.get("model_patch", "").strip()]
    if not non_empty:
        return results_for_instance[0]
    return max(non_empty, key=lambda r: len(r["model_patch"]))


def write_best_of_n_predictions(
    all_results: list[dict],
    output_path: Path,
) -> Path:
    """
    Write a "best-of-N" predictions file, picking the best patch per instance.
    """
    by_instance: dict[str, list[dict]] = {}
    for r in all_results:
        by_instance.setdefault(r["instance_id"], []).append(r)

    best_results = [pick_best_patch(group) for group in by_instance.values()]
    return write_predictions(best_results, output_path, "best_of_n")


def prepare_eval_images(
    instance_ids: list[str],
    dataset_name: str = "princeton-nlp/SWE-bench_Lite",
    max_workers: int = 1,
):
    """
    Pre-build Docker images needed for SWE-bench evaluation.
    """
    from swebench.harness.prepare_images import main as prepare_main

    logger.info(f"Preparing Docker images for {len(instance_ids)} instances: {instance_ids}")

    try:
        prepare_main(
            dataset_name=dataset_name,
            split="test",
            instance_ids=instance_ids,
            max_workers=max_workers,
            force_rebuild=False,
            open_file_limit=4096,
            namespace=None,
            tag="latest",
            env_image_tag="latest",
        )
        logger.info("Docker images prepared successfully")
    except Exception as e:
        logger.error(f"Failed to prepare Docker images: {e}")
        raise


def run_swebench_evaluation(
    predictions_path: Path,
    run_id: str,
    max_workers: int = 4,
    dataset_name: str = "princeton-nlp/SWE-bench_Lite",
) -> dict:
    """
    Run the official SWE-bench evaluation harness in-process.

    This spawns Docker containers for each instance, applies the patch,
    runs tests, and reports pass/fail.

    Args:
        predictions_path: Path to the predictions JSONL file
        run_id: Unique identifier for this evaluation run
        max_workers: Number of parallel Docker workers
        dataset_name: HuggingFace dataset name

    Returns:
        Dict with evaluation results
    """
    logger.info(
        f"Running SWE-bench evaluation: {predictions_path} "
        f"(run_id={run_id}, workers={max_workers})"
    )

    try:
        from swebench.harness.run_evaluation import main as eval_main

        eval_main(
            dataset_name=dataset_name,
            split="test",
            instance_ids=[],
            predictions_path=str(predictions_path),
            max_workers=max_workers,
            force_rebuild=False,
            cache_level="env",
            clean=False,
            open_file_limit=4096,
            run_id=run_id,
            timeout=1800,
            namespace=None,
            rewrite_reports=False,
            modal=False,
        )

        logger.info("Evaluation completed successfully")
        return parse_evaluation_output(run_id)

    except Exception as e:
        logger.warning(f"Evaluation raised exception (may be non-fatal): {e}")
        results = parse_evaluation_output(run_id)
        if results["total"] > 0:
            logger.info(
                f"Found {results['total']} results despite exception "
                f"(passed={results['passed']}, failed={results['failed']})"
            )
            return results
        return {"success": False, "error": str(e), "run_id": run_id}


def parse_evaluation_output(run_id: str) -> dict:
    """Parse the SWE-bench evaluation output for results."""
    results = {
        "success": True,
        "run_id": run_id,
        "instances": {},
        "total": 0,
        "passed": 0,
        "failed": 0,
    }

    # SWE-bench writes per-instance reports to:
    #   logs/run_evaluation/<run_id>/<model_name>/<instance_id>/report.json
    search_dirs = [
        Path(f"logs/run_evaluation/{run_id}"),
        Path(f"logs/{run_id}"),
        Path(f"results/{run_id}"),
    ]

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for result_file in search_dir.rglob("report.json"):
            try:
                with open(result_file) as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for instance_id, status in data.items():
                        if isinstance(status, dict) and instance_id not in results["instances"]:
                            results["instances"][instance_id] = status
                            results["total"] += 1
                            if status.get("resolved", False):
                                results["passed"] += 1
                            else:
                                results["failed"] += 1
                logger.info(f"Parsed results from {result_file}")
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to parse {result_file}: {e}")
                continue

    if results["total"] == 0:
        logger.warning(f"No evaluation results found for run_id={run_id}")
        results["success"] = False

    return results


def print_evaluation_summary(eval_results: dict):
    """Print a human-readable summary of evaluation results."""
    print("\n" + "=" * 60)
    print("SWE-bench Evaluation Results")
    print("=" * 60)
    print(f"Run ID:  {eval_results.get('run_id', 'unknown')}")
    print(f"Total:   {eval_results.get('total', 0)}")
    print(f"Passed:  {eval_results.get('passed', 0)}")
    print(f"Failed:  {eval_results.get('failed', 0)}")

    total = eval_results.get("total", 0)
    if total > 0:
        rate = eval_results.get("passed", 0) / total * 100
        print(f"Rate:    {rate:.1f}%")

    instances = eval_results.get("instances", {})
    if instances:
        print("\nPer-instance results:")
        for iid, status in sorted(instances.items()):
            resolved = status.get("resolved", False)
            mark = "PASS" if resolved else "FAIL"
            print(f"  [{mark}] {iid}")

    print("=" * 60 + "\n")
