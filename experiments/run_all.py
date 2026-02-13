#!/usr/bin/env python3
"""
Master experiment runner for the uncertainty-injection perturbation study.

Runs all conditions sequentially, evaluates patches, and generates a final report.

Usage:
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    uv run python experiments/run_all.py
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Ensure SSL works
os.environ.setdefault("SSL_CERT_FILE", "/etc/ssl/certs/ca-certificates.crt")
os.environ.setdefault("REQUESTS_CA_BUNDLE", "/etc/ssl/certs/ca-certificates.crt")

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from kekule.benchmarks.config import HarnessConfig
from kekule.benchmarks.harness import run_experiment, load_solver
from kekule.benchmarks.evaluator import (
    run_swebench_evaluation,
    print_evaluation_summary,
    prepare_eval_images,
)
from kekule.benchmarks.task_selector import select_tasks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("experiment_runner")

# ── Experiment definitions ──────────────────────────────────────────────────

TASK_IDS = [
    "django__django-16379",
    "django__django-14915",
    "pytest-dev__pytest-5413",
]

EXPERIMENTS = [
    {
        "name": "ansh-baseline-no-perturbation",
        "solver": "perturbation_swarm",
        "intensity": 0.0,
        "description": "Swarm baseline — no uncertainty injection",
    },
    {
        "name": "ansh-perturbation-low",
        "solver": "perturbation_swarm",
        "intensity": 0.05,
        "description": "Swarm with low uncertainty (0.05)",
    },
    # We already ran medium (0.10) — re-run for clean data in same dir structure
    {
        "name": "ansh-perturbation-medium",
        "solver": "perturbation_swarm",
        "intensity": 0.10,
        "description": "Swarm with medium uncertainty (0.10)",
    },
    {
        "name": "ansh-perturbation-high",
        "solver": "perturbation_swarm",
        "intensity": 0.20,
        "description": "Swarm with high uncertainty (0.20)",
    },
    {
        "name": "ansh-single-agent-control",
        "solver": "default",
        "intensity": 0.0,
        "description": "Single-agent control — no swarm, no perturbation",
    },
]

EXPERIMENT_ROOT = ROOT / "experiments" / "uncertainty-injection"
ALL_RESULTS_DIR = EXPERIMENT_ROOT / "results"


# ── Docker image preparation ───────────────────────────────────────────────

def ensure_eval_images():
    """Build SWE-bench Docker eval images for all task IDs."""
    logger.info("=" * 60)
    logger.info("STEP 0: Preparing Docker eval images")
    logger.info("=" * 60)

    try:
        prepare_eval_images(TASK_IDS, max_workers=1)
        logger.info("Docker images ready")
    except Exception as e:
        logger.warning(f"Image preparation error (may be non-fatal): {e}")
        # Check if images exist anyway
        for tid in TASK_IDS:
            result = subprocess.run(
                ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
                capture_output=True, text=True, timeout=30,
            )
            logger.info(f"Available images matching eval:\n{result.stdout[:500]}")


# ── Run a single experiment ─────────────────────────────────────────────────

async def run_single_experiment(exp: dict, exp_index: int) -> dict:
    """Run one experiment condition and return metadata."""
    name = exp["name"]
    solver = exp["solver"]
    intensity = exp["intensity"]

    logger.info("=" * 60)
    logger.info(f"EXPERIMENT {exp_index + 1}/{len(EXPERIMENTS)}: {name}")
    logger.info(f"  Solver:    {solver}")
    logger.info(f"  Intensity: {intensity}")
    logger.info(f"  Description: {exp['description']}")
    logger.info("=" * 60)

    # Set perturbation intensity
    os.environ["PERTURBATION_INTENSITY"] = str(intensity)

    # Configure paths — each experiment gets its own results + workspaces
    results_dir = ALL_RESULTS_DIR / name
    workspaces_dir = ROOT / "workspaces" / name

    # Clean workspace for fresh run
    if workspaces_dir.exists():
        shutil.rmtree(workspaces_dir, ignore_errors=True)
    workspaces_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    config = HarnessConfig(
        experiment_name=name,
        solver=solver,
        num_problems=3,
        agents_per_problem=1,
        num_iterations=1,
        results_dir=results_dir,
        workspaces_dir=workspaces_dir,
        task_ids=TASK_IDS,
        # Langfuse — pick up from env vars if set
        langfuse_secret_key=os.environ.get("LANGFUSE_SECRET_KEY", ""),
        langfuse_public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
        langfuse_base_url=os.environ.get("LANGFUSE_BASE_URL", ""),
    )

    start = time.time()
    try:
        await run_experiment(config, skip_eval=True)
        elapsed = time.time() - start
        logger.info(f"Experiment '{name}' completed in {elapsed:.0f}s")

        # Load raw results
        raw_path = results_dir / "iteration_0" / "raw_results.json"
        if raw_path.exists():
            with open(raw_path) as f:
                raw_results = json.load(f)
        else:
            raw_results = []

        return {
            "name": name,
            "solver": solver,
            "intensity": intensity,
            "elapsed_s": elapsed,
            "raw_results": raw_results,
            "error": None,
        }
    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"Experiment '{name}' FAILED after {elapsed:.0f}s: {e}")
        return {
            "name": name,
            "solver": solver,
            "intensity": intensity,
            "elapsed_s": elapsed,
            "raw_results": [],
            "error": str(e),
        }


# ── Evaluate all experiments ────────────────────────────────────────────────

def evaluate_experiment(exp_result: dict) -> dict:
    """Run SWE-bench Docker eval on one experiment's predictions."""
    name = exp_result["name"]
    results_dir = ALL_RESULTS_DIR / name / "iteration_0"
    predictions_file = results_dir / "predictions_best_of_n.jsonl"

    if not predictions_file.exists():
        logger.warning(f"No predictions file for {name}, skipping eval")
        return {"name": name, "eval_results": None, "error": "no predictions"}

    logger.info(f"Evaluating {name}...")
    try:
        eval_results = run_swebench_evaluation(
            predictions_file,
            run_id=f"eval-{name}",
            max_workers=1,
        )
        print_evaluation_summary(eval_results)
        return {"name": name, "eval_results": eval_results, "error": None}
    except Exception as e:
        logger.error(f"Eval failed for {name}: {e}")
        return {"name": name, "eval_results": None, "error": str(e)}


# ── Generate report and graphs ──────────────────────────────────────────────

def generate_report(experiment_results: list[dict], eval_results: list[dict]):
    """Generate the final report with analysis and matplotlib graphs."""
    logger.info("=" * 60)
    logger.info("GENERATING FINAL REPORT")
    logger.info("=" * 60)

    # Collect data for analysis
    data = []
    for exp_r in experiment_results:
        eval_r = next(
            (e for e in eval_results if e["name"] == exp_r["name"]),
            {"eval_results": None},
        )
        raw = exp_r.get("raw_results", [])

        total_cost = sum(r.get("cost_usd", 0) for r in raw)
        total_turns = sum(r.get("num_turns", 0) for r in raw)
        patches = sum(1 for r in raw if r.get("model_patch", "").strip())
        durations = [r.get("duration_s", 0) for r in raw]
        avg_duration = sum(durations) / len(durations) if durations else 0

        # Eval results
        er = eval_r.get("eval_results")
        resolved = 0
        total_eval = 0
        per_task_results = {}
        if er and isinstance(er, dict):
            resolved = er.get("passed", 0)
            total_eval = er.get("total", 0)
            per_task_results = er.get("instances", {})

        data.append({
            "name": exp_r["name"],
            "solver": exp_r["solver"],
            "intensity": exp_r["intensity"],
            "description": next(
                (e["description"] for e in EXPERIMENTS if e["name"] == exp_r["name"]),
                "",
            ),
            "total_cost": total_cost,
            "total_turns": total_turns,
            "patches_produced": patches,
            "avg_duration_s": avg_duration,
            "resolved": resolved,
            "total_eval": total_eval,
            "per_task": per_task_results,
            "error": exp_r.get("error"),
            "raw_results": raw,
        })

    # Save aggregated data
    agg_path = EXPERIMENT_ROOT / "aggregated_results.json"
    with open(agg_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    logger.info(f"Saved aggregated results to {agg_path}")

    # Generate graphs
    try:
        _generate_graphs(data)
    except Exception as e:
        logger.error(f"Graph generation failed: {e}")

    # Generate markdown report
    _generate_markdown_report(data)


def _generate_graphs(data: list[dict]):
    """Generate matplotlib graphs comparing experiments."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mtick

    graphs_dir = EXPERIMENT_ROOT / "graphs"
    graphs_dir.mkdir(exist_ok=True)

    # Separate swarm experiments from single-agent control
    swarm_data = [d for d in data if d["solver"] == "perturbation_swarm"]
    control_data = [d for d in data if d["solver"] == "default"]

    # Sort swarm data by intensity
    swarm_data.sort(key=lambda d: d["intensity"])

    intensities = [d["intensity"] for d in swarm_data]
    intensity_labels = [str(d["intensity"]) for d in swarm_data]

    # Color scheme
    swarm_color = "#4A90D9"
    control_color = "#E74C3C"
    pass_color = "#2ECC71"
    fail_color = "#E74C3C"

    # ── Graph 1: Resolve Rate vs Perturbation Intensity ──────────────────
    fig, ax = plt.subplots(figsize=(8, 5))

    resolve_rates = []
    for d in swarm_data:
        total = d["total_eval"] if d["total_eval"] > 0 else len(TASK_IDS)
        rate = d["resolved"] / total * 100 if total > 0 else 0
        resolve_rates.append(rate)

    ax.bar(intensity_labels, resolve_rates, color=swarm_color, alpha=0.8,
           label="Swarm", width=0.5)

    # Add control as horizontal line
    if control_data:
        ctrl = control_data[0]
        ctrl_total = ctrl["total_eval"] if ctrl["total_eval"] > 0 else len(TASK_IDS)
        ctrl_rate = ctrl["resolved"] / ctrl_total * 100 if ctrl_total > 0 else 0
        ax.axhline(y=ctrl_rate, color=control_color, linestyle="--", linewidth=2,
                   label=f"Single Agent ({ctrl_rate:.0f}%)")

    ax.set_xlabel("Perturbation Intensity")
    ax.set_ylabel("Resolve Rate (%)")
    ax.set_title("SWE-bench Resolve Rate vs Uncertainty Injection")
    ax.set_ylim(0, 105)
    ax.yaxis.set_major_formatter(mtick.PercentFormatter())
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(graphs_dir / "resolve_rate_vs_intensity.png", dpi=150)
    plt.close(fig)
    logger.info("Generated: resolve_rate_vs_intensity.png")

    # ── Graph 2: Cost vs Perturbation Intensity ──────────────────────────
    fig, ax = plt.subplots(figsize=(8, 5))

    costs = [d["total_cost"] for d in swarm_data]
    ax.bar(intensity_labels, costs, color=swarm_color, alpha=0.8,
           label="Swarm", width=0.5)

    if control_data:
        ctrl_cost = control_data[0]["total_cost"]
        ax.axhline(y=ctrl_cost, color=control_color, linestyle="--", linewidth=2,
                   label=f"Single Agent (${ctrl_cost:.2f})")

    ax.set_xlabel("Perturbation Intensity")
    ax.set_ylabel("Total Cost (USD)")
    ax.set_title("API Cost vs Uncertainty Injection")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(graphs_dir / "cost_vs_intensity.png", dpi=150)
    plt.close(fig)
    logger.info("Generated: cost_vs_intensity.png")

    # ── Graph 3: Turns vs Perturbation Intensity ─────────────────────────
    fig, ax = plt.subplots(figsize=(8, 5))

    turns = [d["total_turns"] for d in swarm_data]
    ax.bar(intensity_labels, turns, color=swarm_color, alpha=0.8,
           label="Swarm", width=0.5)

    if control_data:
        ctrl_turns = control_data[0]["total_turns"]
        ax.axhline(y=ctrl_turns, color=control_color, linestyle="--", linewidth=2,
                   label=f"Single Agent ({ctrl_turns})")

    ax.set_xlabel("Perturbation Intensity")
    ax.set_ylabel("Total Agent Turns")
    ax.set_title("Agent Turns vs Uncertainty Injection")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(graphs_dir / "turns_vs_intensity.png", dpi=150)
    plt.close(fig)
    logger.info("Generated: turns_vs_intensity.png")

    # ── Graph 4: Per-task results heatmap ────────────────────────────────
    fig, ax = plt.subplots(figsize=(10, 5))

    exp_names = [d["name"].replace("ansh-", "") for d in data]
    task_ids_short = [t.split("__")[-1] for t in TASK_IDS]

    heatmap_data = []
    for d in data:
        row = []
        for tid in TASK_IDS:
            per_task = d.get("per_task", {})
            if tid in per_task:
                resolved = per_task[tid].get("resolved", False)
                row.append(1 if resolved else 0)
            else:
                row.append(-1)  # No eval data
        heatmap_data.append(row)

    import numpy as np
    hm = np.array(heatmap_data)

    # Custom colormap: -1=gray, 0=red, 1=green
    from matplotlib.colors import ListedColormap
    cmap = ListedColormap(["#cccccc", fail_color, pass_color])

    im = ax.imshow(hm, cmap=cmap, vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(range(len(task_ids_short)))
    ax.set_xticklabels(task_ids_short, rotation=30, ha="right")
    ax.set_yticks(range(len(exp_names)))
    ax.set_yticklabels(exp_names)
    ax.set_title("Per-Task Resolution (Green=Pass, Red=Fail, Gray=No Eval)")

    # Add text labels
    for i in range(len(exp_names)):
        for j in range(len(task_ids_short)):
            val = hm[i, j]
            text = "PASS" if val == 1 else ("FAIL" if val == 0 else "N/A")
            color = "white" if val != -1 else "black"
            ax.text(j, i, text, ha="center", va="center", fontsize=9,
                    fontweight="bold", color=color)

    fig.tight_layout()
    fig.savefig(graphs_dir / "per_task_heatmap.png", dpi=150)
    plt.close(fig)
    logger.info("Generated: per_task_heatmap.png")

    # ── Graph 5: Duration vs Intensity ───────────────────────────────────
    fig, ax = plt.subplots(figsize=(8, 5))

    durations = [d["avg_duration_s"] / 60 for d in swarm_data]  # convert to minutes
    ax.bar(intensity_labels, durations, color=swarm_color, alpha=0.8,
           label="Swarm", width=0.5)

    if control_data:
        ctrl_dur = control_data[0]["avg_duration_s"] / 60
        ax.axhline(y=ctrl_dur, color=control_color, linestyle="--", linewidth=2,
                   label=f"Single Agent ({ctrl_dur:.1f} min)")

    ax.set_xlabel("Perturbation Intensity")
    ax.set_ylabel("Avg Duration per Task (minutes)")
    ax.set_title("Execution Time vs Uncertainty Injection")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(graphs_dir / "duration_vs_intensity.png", dpi=150)
    plt.close(fig)
    logger.info("Generated: duration_vs_intensity.png")

    # ── Graph 6: Combined overview ───────────────────────────────────────
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))

    # Resolve rate
    ax = axes[0]
    all_names = [d["name"].replace("ansh-", "").replace("perturbation-", "P=") for d in data]
    all_resolve = []
    colors = []
    for d in data:
        total = d["total_eval"] if d["total_eval"] > 0 else len(TASK_IDS)
        rate = d["resolved"] / total * 100 if total > 0 else 0
        all_resolve.append(rate)
        colors.append(control_color if d["solver"] == "default" else swarm_color)
    ax.barh(all_names, all_resolve, color=colors, alpha=0.8)
    ax.set_xlabel("Resolve Rate (%)")
    ax.set_title("Resolve Rate")
    ax.set_xlim(0, 105)

    # Cost
    ax = axes[1]
    all_costs = [d["total_cost"] for d in data]
    ax.barh(all_names, all_costs, color=colors, alpha=0.8)
    ax.set_xlabel("Cost (USD)")
    ax.set_title("Total Cost")

    # Turns
    ax = axes[2]
    all_turns = [d["total_turns"] for d in data]
    ax.barh(all_names, all_turns, color=colors, alpha=0.8)
    ax.set_xlabel("Turns")
    ax.set_title("Total Turns")

    fig.suptitle("Experiment Comparison Overview", fontsize=14, fontweight="bold")
    fig.tight_layout()
    fig.savefig(graphs_dir / "overview_comparison.png", dpi=150)
    plt.close(fig)
    logger.info("Generated: overview_comparison.png")


def _generate_markdown_report(data: list[dict]):
    """Generate the final markdown report."""
    report_path = EXPERIMENT_ROOT / "final_report.md"

    lines = [
        "# Uncertainty Injection Experiment — Final Report",
        "",
        f"**Generated**: {time.strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Tasks**: {', '.join(TASK_IDS)}",
        f"**Experiments**: {len(data)}",
        "",
        "## Summary",
        "",
        "| Experiment | Solver | Intensity | Resolved | Patches | Cost (USD) | Turns | Avg Time (min) |",
        "|------------|--------|-----------|----------|---------|------------|-------|----------------|",
    ]

    for d in data:
        total = d["total_eval"] if d["total_eval"] > 0 else len(TASK_IDS)
        rate = f"{d['resolved']}/{total}"
        lines.append(
            f"| {d['name']} | {d['solver']} | {d['intensity']} | {rate} | "
            f"{d['patches_produced']}/{len(TASK_IDS)} | ${d['total_cost']:.2f} | "
            f"{d['total_turns']} | {d['avg_duration_s']/60:.1f} |"
        )

    lines.extend([
        "",
        "## Graphs",
        "",
        "### Resolve Rate vs Perturbation Intensity",
        "![Resolve Rate](graphs/resolve_rate_vs_intensity.png)",
        "",
        "### Cost vs Perturbation Intensity",
        "![Cost](graphs/cost_vs_intensity.png)",
        "",
        "### Agent Turns vs Perturbation Intensity",
        "![Turns](graphs/turns_vs_intensity.png)",
        "",
        "### Execution Time vs Perturbation Intensity",
        "![Duration](graphs/duration_vs_intensity.png)",
        "",
        "### Per-Task Resolution Heatmap",
        "![Heatmap](graphs/per_task_heatmap.png)",
        "",
        "### Combined Overview",
        "![Overview](graphs/overview_comparison.png)",
        "",
        "## Per-Task Results",
        "",
    ])

    for tid in TASK_IDS:
        lines.append(f"### {tid}")
        lines.append("")
        lines.append("| Experiment | Resolved | Patch Size |")
        lines.append("|------------|----------|------------|")
        for d in data:
            per_task = d.get("per_task", {})
            resolved = "N/A"
            if tid in per_task:
                resolved = "PASS" if per_task[tid].get("resolved") else "FAIL"
            patch_size = "—"
            for r in d.get("raw_results", []):
                if r.get("instance_id") == tid:
                    ps = len(r.get("model_patch", ""))
                    patch_size = f"{ps} bytes" if ps > 0 else "empty"
            lines.append(f"| {d['name']} | {resolved} | {patch_size} |")
        lines.append("")

    # Analysis section
    lines.extend([
        "## Analysis",
        "",
        "### Key Findings",
        "",
    ])

    # Auto-generate findings
    swarm_data = [d for d in data if d["solver"] == "perturbation_swarm"]
    control_data = [d for d in data if d["solver"] == "default"]

    if swarm_data:
        best_swarm = max(swarm_data, key=lambda d: d["resolved"])
        worst_swarm = min(swarm_data, key=lambda d: d["resolved"])
        cheapest = min(swarm_data, key=lambda d: d["total_cost"])

        lines.append(f"1. **Best swarm condition**: {best_swarm['name']} "
                     f"(intensity={best_swarm['intensity']}, "
                     f"resolved={best_swarm['resolved']}/{best_swarm['total_eval'] or len(TASK_IDS)})")
        lines.append(f"2. **Cheapest swarm condition**: {cheapest['name']} "
                     f"(${cheapest['total_cost']:.2f})")

        if control_data:
            ctrl = control_data[0]
            ctrl_total = ctrl["total_eval"] if ctrl["total_eval"] > 0 else len(TASK_IDS)
            lines.append(f"3. **Single agent control**: resolved "
                        f"{ctrl['resolved']}/{ctrl_total}, "
                        f"cost ${ctrl['total_cost']:.2f}, "
                        f"{ctrl['total_turns']} turns")

            if best_swarm["resolved"] > ctrl["resolved"]:
                lines.append("4. **Swarm outperforms single agent** on resolve rate")
            elif best_swarm["resolved"] == ctrl["resolved"]:
                lines.append("4. **Swarm matches single agent** on resolve rate")
            else:
                lines.append("4. **Single agent outperforms swarm** on resolve rate")

        # Cost analysis
        avg_swarm_cost = sum(d["total_cost"] for d in swarm_data) / len(swarm_data)
        if control_data:
            cost_ratio = avg_swarm_cost / max(control_data[0]["total_cost"], 0.01)
            lines.append(f"5. **Cost ratio** (swarm avg / single): {cost_ratio:.1f}x")

    lines.extend([
        "",
        "### Perturbation Effect",
        "",
    ])

    if len(swarm_data) >= 2:
        baseline_d = next((d for d in swarm_data if d["intensity"] == 0.0), None)
        if baseline_d:
            lines.append(
                f"- Baseline (0.0) resolve rate: "
                f"{baseline_d['resolved']}/{baseline_d['total_eval'] or len(TASK_IDS)}"
            )
            for d in swarm_data:
                if d["intensity"] > 0:
                    lines.append(
                        f"- Intensity {d['intensity']}: "
                        f"resolved={d['resolved']}/{d['total_eval'] or len(TASK_IDS)}, "
                        f"cost_delta={d['total_cost'] - baseline_d['total_cost']:+.2f}"
                    )

    lines.extend([
        "",
        "### Methodology",
        "",
        "- **Swarm architecture**: 3 agents per task, self-organizing via shared ledger",
        "- **Planning**: Lightweight planner assigns initial roles (2-4 per task)",
        "- **Coordination**: Agents communicate via `swarm_ledger/` directory",
        "- **Verification**: Agents cross-verify fixes by running tests",
        "- **Patch selection**: Priority = endorsed fix > single proposed fix > git diff",
        "- **Control**: Single agent with default solver, same tasks and tools",
        "- **Perturbation**: Uncertainty text injected into swarm agent prompts only",
        f"- **Tasks**: {len(TASK_IDS)} SWE-bench Lite instances",
        "- **Evaluation**: Official SWE-bench Docker harness",
        "",
        "## Raw Data",
        "",
        "See `aggregated_results.json` for full structured data.",
        "",
    ])

    report_path.write_text("\n".join(lines))
    logger.info(f"Final report written to {report_path}")


# ── Main entry point ────────────────────────────────────────────────────────

async def main():
    total_start = time.time()

    logger.info("=" * 60)
    logger.info("UNCERTAINTY INJECTION EXPERIMENT SUITE")
    logger.info(f"Running {len(EXPERIMENTS)} experiments on {len(TASK_IDS)} tasks")
    logger.info("=" * 60)

    # Step 0: Prepare Docker eval images
    try:
        ensure_eval_images()
    except Exception as e:
        logger.warning(f"Image prep issue (will retry at eval time): {e}")

    # Step 1: Run all experiments sequentially
    experiment_results = []
    for i, exp in enumerate(EXPERIMENTS):
        result = await run_single_experiment(exp, i)
        experiment_results.append(result)

        # Save intermediate results after each experiment
        intermediate_path = EXPERIMENT_ROOT / "intermediate_results.json"
        with open(intermediate_path, "w") as f:
            json.dump(experiment_results, f, indent=2, default=str)
        logger.info(f"Saved intermediate results ({i+1}/{len(EXPERIMENTS)} done)")

    # Step 2: Run evaluations on all experiments
    logger.info("=" * 60)
    logger.info("RUNNING EVALUATIONS ON ALL EXPERIMENTS")
    logger.info("=" * 60)

    eval_results = []
    for exp_result in experiment_results:
        if exp_result.get("error"):
            logger.warning(f"Skipping eval for failed experiment: {exp_result['name']}")
            eval_results.append({
                "name": exp_result["name"],
                "eval_results": None,
                "error": "experiment_failed",
            })
            continue
        er = evaluate_experiment(exp_result)
        eval_results.append(er)

    # Save eval results
    eval_path = EXPERIMENT_ROOT / "eval_results.json"
    with open(eval_path, "w") as f:
        json.dump(eval_results, f, indent=2, default=str)

    # Step 3: Generate report and graphs
    generate_report(experiment_results, eval_results)

    total_elapsed = time.time() - total_start
    logger.info("=" * 60)
    logger.info(f"ALL DONE in {total_elapsed/60:.1f} minutes")
    logger.info(f"Results: {EXPERIMENT_ROOT}")
    logger.info(f"Report:  {EXPERIMENT_ROOT / 'final_report.md'}")
    logger.info(f"Graphs:  {EXPERIMENT_ROOT / 'graphs/'}")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
