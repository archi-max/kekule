#!/usr/bin/env python3
"""
Run the tool-I/O perturbation experiment matrix (baseline/low/medium/high).

This runner is seed-aware and records both configured and observed fire rates.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402
from kekule.benchmarks.config import HarnessConfig  # noqa: E402
from kekule.benchmarks.harness import run_experiment  # noqa: E402
from kekule.benchmarks.patch_hygiene import sanitize_patch  # noqa: E402
from kekule.benchmarks.evaluator import (  # noqa: E402
    print_evaluation_summary,
    run_swebench_evaluation,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("tool_io_runner")

# Load project .env for LANGFUSE_* and any run-time overrides.
load_dotenv(ROOT / ".env", override=False)


TASK_IDS = [
    "django__django-16379",
    "django__django-14915",
    "pytest-dev__pytest-5413",
]

SEEDS = [1, 2, 3]

CONDITIONS = [
    {
        "name": "toolio-baseline",
        "description": "No perturbation",
        "mode": "off",
        "intensity": 0.0,
    },
    {
        "name": "toolio-low",
        "description": "Tool I/O degradation with p=0.05",
        "mode": "tool_io_degrade",
        "intensity": 0.05,
    },
    {
        "name": "toolio-medium",
        "description": "Tool I/O degradation with p=0.10",
        "mode": "tool_io_degrade",
        "intensity": 0.10,
    },
    {
        "name": "toolio-high",
        "description": "Tool I/O degradation with p=0.20",
        "mode": "tool_io_degrade",
        "intensity": 0.20,
    },
]

EXPERIMENT_ROOT = ROOT / "experiments" / "tool-io-reliability"
RESULTS_ROOT = EXPERIMENT_ROOT / "results"


def _sum_field(rows: list[dict], key: str) -> float:
    return sum(float(r.get(key, 0.0) or 0.0) for r in rows)


def _read_json(path: Path, fallback):
    if not path.exists():
        return fallback
    with open(path) as f:
        return json.load(f)


def _aggregate_condition_runs(runs: list[dict]) -> dict:
    total_eval = sum(r.get("eval_total", 0) for r in runs)
    total_passed = sum(r.get("eval_passed", 0) for r in runs)
    total_eligible = sum(r.get("perturbation_eligible", 0) for r in runs)
    total_fired = sum(r.get("perturbation_fired", 0) for r in runs)

    return {
        "runs": len(runs),
        "avg_cost_usd": statistics.fmean(r["total_cost"] for r in runs) if runs else 0.0,
        "avg_turns": statistics.fmean(r["total_turns"] for r in runs) if runs else 0.0,
        "avg_duration_s": statistics.fmean(r["avg_duration_s"] for r in runs) if runs else 0.0,
        "resolve_rate": (total_passed / total_eval) if total_eval > 0 else None,
        "configured_intensity": runs[0]["intensity"] if runs else None,
        "observed_fire_rate": (
            total_fired / total_eligible if total_eligible > 0 else 0.0
        ),
        "perturbation_eligible": total_eligible,
        "perturbation_fired": total_fired,
        "seeds": [r["seed"] for r in runs],
    }


def _enforce_patch_integrity(raw: list[dict], run_name: str) -> list[dict]:
    """
    Sanitize patches in-place and fail fast if any row is unevaluable.
    """
    problems: list[str] = []
    sanitized_rows: list[dict] = []

    for row in raw:
        row_copy = dict(row)
        patch = row_copy.get("model_patch", "")
        if not patch.strip():
            problems.append(f"{row_copy.get('instance_id', 'unknown')}: empty_patch")
            row_copy["model_patch"] = ""
            sanitized_rows.append(row_copy)
            continue

        sanitized = sanitize_patch(
            patch,
            fail_closed_on_special=True,
        )
        if sanitized.rejected:
            problems.append(
                f"{row_copy.get('instance_id', 'unknown')}: rejected({sanitized.reason})"
            )
            row_copy["model_patch"] = ""
        else:
            row_copy["model_patch"] = sanitized.patch
            if not sanitized.patch.strip():
                problems.append(
                    f"{row_copy.get('instance_id', 'unknown')}: empty_after_sanitize"
                )
        sanitized_rows.append(row_copy)

    if problems:
        details = "; ".join(problems)
        raise RuntimeError(
            f"{run_name} produced unevaluable rows ({len(problems)}): {details}"
        )

    return sanitized_rows


async def run_single_condition_seed(condition: dict, seed: int) -> dict:
    run_name = f"{condition['name']}-seed{seed}"
    logger.info(
        "Running %s | mode=%s | p=%.2f",
        run_name,
        condition["mode"],
        condition["intensity"],
    )

    # Set perturbation knobs through env because solver subprocesses/hook contexts
    # read these through HarnessConfig.
    os.environ["PERTURBATION_MODE"] = condition["mode"]
    os.environ["PERTURBATION_INTENSITY"] = str(condition["intensity"])
    os.environ["PERTURBATION_SEED"] = str(seed)
    os.environ["PERTURBATION_TARGET_TOOLS"] = "Bash"
    os.environ["PERTURBATION_PHASE_SCOPE"] = "swarm_phase1"

    results_dir = RESULTS_ROOT / run_name
    workspaces_dir = ROOT / "workspaces" / run_name
    results_dir.mkdir(parents=True, exist_ok=True)
    workspaces_dir.mkdir(parents=True, exist_ok=True)

    config = HarnessConfig(
        experiment_name=run_name,
        solver="perturbation_swarm",
        num_problems=len(TASK_IDS),
        agents_per_problem=1,
        num_iterations=1,
        results_dir=results_dir,
        workspaces_dir=workspaces_dir,
        task_ids=TASK_IDS,
        perturbation_mode=condition["mode"],
        perturbation_intensity=condition["intensity"],
        perturbation_target_tools=["Bash"],
        perturbation_seed=seed,
        perturbation_phase_scope="swarm_phase1",
        langfuse_secret_key=os.environ.get("LANGFUSE_SECRET_KEY", ""),
        langfuse_public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
        langfuse_base_url=os.environ.get("LANGFUSE_BASE_URL", ""),
    )

    start = time.time()
    await run_experiment(config, skip_eval=True)
    elapsed = time.time() - start

    raw_path = results_dir / "iteration_0" / "raw_results.json"
    raw = _enforce_patch_integrity(_read_json(raw_path, []), run_name)
    raw_path.write_text(json.dumps(raw, indent=2))

    eval_total = 0
    eval_passed = 0
    if os.environ.get("RUN_TOOLIO_EVAL", "0") == "1":
        predictions = results_dir / "iteration_0" / "predictions_best_of_n.jsonl"
        if predictions.exists():
            eval_results = run_swebench_evaluation(
                predictions,
                run_id=f"eval-{run_name}",
                max_workers=1,
            )
            print_evaluation_summary(eval_results)
            eval_total = int(eval_results.get("total", 0))
            eval_passed = int(eval_results.get("passed", 0))

    return {
        "name": run_name,
        "condition": condition["name"],
        "description": condition["description"],
        "mode": condition["mode"],
        "intensity": condition["intensity"],
        "seed": seed,
        "elapsed_s": elapsed,
        "total_cost": _sum_field(raw, "cost_usd"),
        "total_turns": int(_sum_field(raw, "num_turns")),
        "avg_duration_s": (
            statistics.fmean(float(r.get("duration_s", 0.0) or 0.0) for r in raw)
            if raw
            else 0.0
        ),
        "patches_produced": sum(1 for r in raw if (r.get("model_patch") or "").strip()),
        "perturbation_eligible": int(_sum_field(raw, "perturbation_eligible")),
        "perturbation_fired": int(_sum_field(raw, "perturbation_fired")),
        "eval_total": eval_total,
        "eval_passed": eval_passed,
        "raw_results": raw,
    }


async def main():
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    runs: list[dict] = []
    for condition in CONDITIONS:
        for seed in SEEDS:
            runs.append(await run_single_condition_seed(condition, seed))

    by_condition: dict[str, list[dict]] = {}
    for run in runs:
        by_condition.setdefault(run["condition"], []).append(run)

    aggregated = {
        condition_name: _aggregate_condition_runs(condition_runs)
        for condition_name, condition_runs in by_condition.items()
    }

    (EXPERIMENT_ROOT / "raw_runs.json").write_text(json.dumps(runs, indent=2))
    (EXPERIMENT_ROOT / "aggregated_results.json").write_text(
        json.dumps(aggregated, indent=2)
    )

    lines = [
        "# Tool I/O Reliability Experiment",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        "",
        "| Condition | p | observed fire rate | avg cost | avg turns |",
        "|---|---:|---:|---:|---:|",
    ]
    for condition in CONDITIONS:
        c = aggregated.get(condition["name"], {})
        lines.append(
            f"| {condition['name']} | {condition['intensity']:.2f} | "
            f"{c.get('observed_fire_rate', 0.0):.3f} | "
            f"${c.get('avg_cost_usd', 0.0):.2f} | "
            f"{c.get('avg_turns', 0.0):.1f} |"
        )
    (EXPERIMENT_ROOT / "summary.md").write_text("\n".join(lines) + "\n")
    logger.info("Wrote %s", EXPERIMENT_ROOT / "aggregated_results.json")


if __name__ == "__main__":
    asyncio.run(main())
