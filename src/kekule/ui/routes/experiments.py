"""
Self-Improving Experiment dashboard endpoints.

Serves HTML pages for browsing experiment epochs, score progression,
coordinator output, prompt snapshots, and per-task results.

Also provides JSON API endpoints for the React frontend.
"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

router = APIRouter(tags=["experiments"])

_templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

BASE_DIR = Path.cwd()
RESULTS_DIR = BASE_DIR / "results"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scan_experiments(results_dir: Path) -> list[dict]:
    """Scan the results directory for self-improving experiments."""
    if not results_dir.exists():
        return []

    experiments = []

    # Look for directories with scores.json (indicator of self-improving run)
    for scores_file in results_dir.rglob("scores.json"):
        exp_dir = scores_file.parent
        try:
            scores = json.loads(scores_file.read_text())
        except Exception:
            scores = []

        split_info = {}
        split_file = exp_dir / "split.json"
        if split_file.exists():
            try:
                split_info = json.loads(split_file.read_text())
            except Exception:
                pass

        # Determine experiment name from directory
        name = exp_dir.name if exp_dir != results_dir else "default"

        # Count actual epoch directories (may exceed scores.json entries)
        epoch_dirs = sorted(
            d for d in exp_dir.iterdir()
            if d.is_dir() and d.name.startswith("epoch_")
        )
        num_epochs = max(len(scores), len(epoch_dirs))

        # Backfill scores from coordinator_output.json for epochs
        # not yet in scores.json
        scored_epochs = {s.get("epoch", i) for i, s in enumerate(scores)}
        train_ids = split_info.get("train_ids", [])
        test_ids = split_info.get("test_ids", [])

        for epoch_dir in epoch_dirs:
            try:
                epoch_num = int(epoch_dir.name.split("_")[1])
            except (IndexError, ValueError):
                continue
            if epoch_num in scored_epochs:
                continue

            # Try to compute score from raw_results + coordinator
            epoch_score: dict = {"epoch": epoch_num}
            raw_file = epoch_dir / "raw_results.json"
            coord_file = epoch_dir / "coordinator_output.json"

            if coord_file.exists():
                try:
                    coord = json.loads(coord_file.read_text())
                    epoch_score["train_score"] = coord.get("train_score", 0) or 0
                    epoch_score["test_score"] = coord.get("test_score", 0) or 0
                except Exception:
                    pass

            if raw_file.exists():
                try:
                    raw = json.loads(raw_file.read_text())
                    # Count pass/fail per split
                    train_passed = sum(
                        1 for r in raw
                        if r.get("instance_id") in train_ids
                        and r.get("resolved")
                    )
                    test_passed = sum(
                        1 for r in raw
                        if r.get("instance_id") in test_ids
                        and r.get("resolved")
                    )
                    train_in_raw = sum(
                        1 for r in raw if r.get("instance_id") in train_ids
                    )
                    test_in_raw = sum(
                        1 for r in raw if r.get("instance_id") in test_ids
                    )
                    epoch_score.setdefault("train_passed", train_passed)
                    epoch_score.setdefault("train_total", train_in_raw or len(train_ids))
                    epoch_score.setdefault("test_passed", test_passed)
                    epoch_score.setdefault("test_total", test_in_raw or len(test_ids))
                    if "train_score" not in epoch_score and train_in_raw:
                        epoch_score["train_score"] = train_passed / train_in_raw
                    if "test_score" not in epoch_score and test_in_raw:
                        epoch_score["test_score"] = test_passed / test_in_raw
                    epoch_score.setdefault("total_cost_usd", sum(
                        r.get("cost_usd", 0) for r in raw
                    ))
                    epoch_score.setdefault("duration_s", sum(
                        r.get("duration_s", 0) for r in raw
                    ))
                except Exception:
                    pass

            # Fill defaults
            epoch_score.setdefault("train_score", 0)
            epoch_score.setdefault("test_score", 0)
            epoch_score.setdefault("train_passed", 0)
            epoch_score.setdefault("train_total", len(train_ids))
            epoch_score.setdefault("test_passed", 0)
            epoch_score.setdefault("test_total", len(test_ids))
            epoch_score.setdefault("total_cost_usd", 0)
            epoch_score.setdefault("duration_s", 0)

            scores.append(epoch_score)

        # Sort scores by epoch
        scores.sort(key=lambda s: s.get("epoch", 0))

        experiments.append({
            "name": name,
            "path": str(exp_dir),
            "num_epochs": num_epochs,
            "scores": scores,
            "train_ids": train_ids,
            "test_ids": test_ids,
            "train_ratio": split_info.get("train_ratio"),
            "latest_train_score": scores[-1]["train_score"] if scores else 0,
            "latest_test_score": scores[-1]["test_score"] if scores else 0,
            "total_cost": sum(s.get("total_cost_usd", 0) for s in scores),
        })

    return sorted(experiments, key=lambda e: e["name"])


def _build_resolved_lookup(base_dir: Path) -> dict[str, bool]:
    """Build a lookup of instance_id -> resolved from all evaluation reports."""
    resolved: dict[str, bool] = {}
    eval_dir = base_dir / "logs" / "run_evaluation"
    if not eval_dir.exists():
        return resolved

    for run_dir in eval_dir.iterdir():
        if not run_dir.is_dir():
            continue
        for model_dir in run_dir.iterdir():
            if not model_dir.is_dir():
                continue
            for inst_dir in model_dir.iterdir():
                report = inst_dir / "report.json"
                if not report.exists():
                    continue
                try:
                    data = json.loads(report.read_text())
                    iid = next(iter(data))
                    is_resolved = data[iid].get("resolved", False)
                    # Only set to True (don't overwrite a True with a False
                    # from a different run)
                    if is_resolved or iid not in resolved:
                        resolved[iid] = is_resolved
                except Exception:
                    pass

    return resolved


def _load_epoch_data(
    exp_dir: Path, epoch: int, split_info: dict | None = None
) -> dict:
    """Load all data for a specific epoch."""
    epoch_dir = exp_dir / f"epoch_{epoch}"
    data: dict = {"epoch": epoch, "dir": str(epoch_dir)}

    # Raw results — try epoch dir first, then parent dir
    raw_file = epoch_dir / "raw_results.json"
    if raw_file.exists():
        try:
            data["results"] = json.loads(raw_file.read_text())
        except Exception:
            data["results"] = []
    else:
        data["results"] = []

    # If no raw_results, try to reconstruct minimal results from:
    # 1. failure_diagnoses.json (has instance_ids for failed tasks)
    # 2. split_info (has all task IDs)
    # 3. scores.json (has pass/fail counts)
    if not data["results"] and split_info:
        all_ids = split_info.get("train_ids", []) + split_info.get("test_ids", [])
        if all_ids:
            resolved_lookup = _build_resolved_lookup(BASE_DIR)
            data["results"] = [
                {"instance_id": iid, "resolved": resolved_lookup.get(iid, False)}
                for iid in all_ids
            ]

            # Enrich with failure diagnoses if available
            diag_file = epoch_dir / "failure_diagnoses.json"
            if diag_file.exists():
                try:
                    diagnoses = json.loads(diag_file.read_text())
                    diag_by_id = {d["instance_id"]: d for d in diagnoses}
                    for r in data["results"]:
                        diag = diag_by_id.get(r["instance_id"])
                        if diag:
                            r["failure_diagnosis"] = diag
                except Exception:
                    pass

    # Enrich with resolved status and swarm data
    if data["results"]:
        from ..benchmark_scanner import get_epoch_swarm_data

        resolved_lookup = _build_resolved_lookup(BASE_DIR)
        for r in data["results"]:
            if r.get("resolved") is None:
                r["resolved"] = resolved_lookup.get(r.get("instance_id", ""), False)
            # Attach swarm data per task
            r["swarm"] = get_epoch_swarm_data(epoch, r.get("instance_id", ""), BASE_DIR)

    # Coordinator output
    coord_file = epoch_dir / "coordinator_output.json"
    if coord_file.exists():
        try:
            data["coordinator"] = json.loads(coord_file.read_text())
        except Exception:
            data["coordinator"] = None
    else:
        data["coordinator"] = None

    # Prompt snapshot
    snapshot_dir = exp_dir / "prompt_snapshots"
    prompts_file = snapshot_dir / f"epoch_{epoch}_prompts.json"
    config_file = snapshot_dir / f"epoch_{epoch}_config.json"

    if prompts_file.exists():
        try:
            data["prompts"] = json.loads(prompts_file.read_text())
        except Exception:
            data["prompts"] = {}
    else:
        data["prompts"] = {}

    if config_file.exists():
        try:
            data["config"] = json.loads(config_file.read_text())
        except Exception:
            data["config"] = {}
    else:
        data["config"] = {}

    return data


def _load_lessons(exp_dir: Path) -> str:
    """Load accumulated lessons text."""
    lessons_file = exp_dir / "lessons.md"
    if lessons_file.exists():
        return lessons_file.read_text()
    return ""


# ---------------------------------------------------------------------------
# HTML endpoints
# ---------------------------------------------------------------------------


@router.get("/experiments", response_class=HTMLResponse)
async def experiments_page(request: Request):
    """Main experiments listing page."""
    experiments = _scan_experiments(RESULTS_DIR)
    return templates.TemplateResponse(
        "experiments.html",
        {"request": request, "experiments": experiments, "active_nav": "experiments"},
    )


@router.get("/experiments/{name}", response_class=HTMLResponse)
async def experiment_detail_page(name: str, request: Request):
    """Experiment detail page with epoch progression."""
    experiments = _scan_experiments(RESULTS_DIR)
    exp = next((e for e in experiments if e["name"] == name), None)
    if exp is None:
        raise HTTPException(status_code=404, detail=f"Experiment '{name}' not found")

    exp_dir = Path(exp["path"])
    lessons = _load_lessons(exp_dir)

    # Load each epoch's data
    epochs = []
    for i in range(exp["num_epochs"]):
        epochs.append(_load_epoch_data(exp_dir, i, split_info=exp))

    return templates.TemplateResponse(
        "experiment_detail.html",
        {
            "request": request,
            "exp": exp,
            "epochs": epochs,
            "lessons": lessons,
            "active_nav": "experiments",
        },
    )


# ---------------------------------------------------------------------------
# JSON API endpoints
# ---------------------------------------------------------------------------


@router.get("/api/experiments")
async def list_experiments():
    """List all self-improving experiments."""
    return _scan_experiments(RESULTS_DIR)


@router.get("/api/experiments/{name}")
async def get_experiment(name: str):
    """Get full experiment data with all epochs."""
    experiments = _scan_experiments(RESULTS_DIR)
    exp = next((e for e in experiments if e["name"] == name), None)
    if exp is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    exp_dir = Path(exp["path"])
    exp["lessons"] = _load_lessons(exp_dir)
    exp["epochs"] = []
    for i in range(exp["num_epochs"]):
        exp["epochs"].append(_load_epoch_data(exp_dir, i))

    return exp


@router.get("/api/experiments/{name}/epoch/{epoch}")
async def get_epoch(name: str, epoch: int):
    """Get data for a specific epoch."""
    experiments = _scan_experiments(RESULTS_DIR)
    exp = next((e for e in experiments if e["name"] == name), None)
    if exp is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    exp_dir = Path(exp["path"])
    return _load_epoch_data(exp_dir, epoch, split_info=exp)


@router.get("/api/experiments/{name}/prompts")
async def get_experiment_prompts(name: str):
    """Get the current prompts directory for an experiment."""
    experiments = _scan_experiments(RESULTS_DIR)
    exp = next((e for e in experiments if e["name"] == name), None)
    if exp is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    exp_dir = Path(exp["path"])
    prompts_dir = exp_dir / "prompts"
    prompts = {}
    if prompts_dir.exists():
        for f in prompts_dir.glob("*.md"):
            prompts[f.stem] = f.read_text()
    return prompts


@router.get("/api/experiments/{name}/scores")
async def get_experiment_scores(name: str):
    """Get score progression for charting."""
    experiments = _scan_experiments(RESULTS_DIR)
    exp = next((e for e in experiments if e["name"] == name), None)
    if exp is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    return {
        "name": name,
        "scores": exp["scores"],
        "train_ids": exp["train_ids"],
        "test_ids": exp["test_ids"],
    }
