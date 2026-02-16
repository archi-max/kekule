"""
Benchmark dashboard endpoints.

Serves HTML pages for browsing SWE-bench evaluation runs, per-task results,
test breakdowns, AI failure summaries, and agent chat logs.

Also provides JSON API endpoints for programmatic access.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..benchmark_scanner import (
    get_agent_findings,
    get_agent_logs,
    get_ai_summary,
    get_fault_analysis,
    get_swarm_broadcast,
    get_swarm_roles,
    get_task_detail,
    get_test_output,
    save_ai_summary,
    scan_all_runs,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["benchmarks"])

_templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

BASE_DIR = Path.cwd()


# ---------------------------------------------------------------------------
# HTML endpoints
# ---------------------------------------------------------------------------


@router.get("/benchmarks", response_class=HTMLResponse)
async def benchmarks_page(request: Request):
    """Main benchmark listing page."""
    runs = scan_all_runs(BASE_DIR)
    return templates.TemplateResponse(
        "benchmarks.html",
        {"request": request, "runs": runs, "active_nav": "benchmarks"},
    )


@router.get("/benchmarks/{run_id}", response_class=HTMLResponse)
async def run_detail_page(run_id: str, request: Request):
    """Run detail page showing per-task pass/fail table."""
    runs = scan_all_runs(BASE_DIR)
    run = next((r for r in runs if r.run_id == run_id), None)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    return templates.TemplateResponse(
        "run_detail.html",
        {"request": request, "run": run, "active_nav": "benchmarks"},
    )


@router.get("/benchmarks/{run_id}/{instance_id}", response_class=HTMLResponse)
async def task_detail_page(run_id: str, instance_id: str, request: Request):
    """Task detail page with test results, agent logs, and raw output."""
    task = get_task_detail(run_id, instance_id, BASE_DIR)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail=f"Task '{instance_id}' not found in run '{run_id}'",
        )

    agent_logs = get_agent_logs(run_id, instance_id, BASE_DIR)
    test_output = get_test_output(run_id, instance_id, BASE_DIR)
    ai_summary = get_ai_summary(run_id, instance_id, BASE_DIR)
    fault_analysis = get_fault_analysis(instance_id, BASE_DIR)
    swarm_broadcast = get_swarm_broadcast(instance_id, BASE_DIR)
    swarm_roles = get_swarm_roles(instance_id, BASE_DIR)
    agent_findings = get_agent_findings(instance_id, BASE_DIR)

    return templates.TemplateResponse(
        "task_detail.html",
        {
            "request": request,
            "run_id": run_id,
            "instance_id": instance_id,
            "task": task,
            "agent_logs": agent_logs,
            "test_output": test_output,
            "ai_summary": ai_summary,
            "fault_analysis": fault_analysis,
            "swarm_broadcast": swarm_broadcast,
            "swarm_roles": swarm_roles,
            "agent_findings": agent_findings,
            "active_nav": "benchmarks",
        },
    )


# ---------------------------------------------------------------------------
# JSON API endpoints
# ---------------------------------------------------------------------------


@router.get("/api/benchmarks")
async def list_runs():
    """List all benchmark runs (JSON)."""
    runs = scan_all_runs(BASE_DIR)
    return [
        {
            "run_id": r.run_id,
            "model": r.model,
            "total": r.total,
            "passed": r.passed,
            "failed": r.failed,
            "pass_rate": r.pass_rate,
            "solver": r.solver,
            "swarm_design": r.swarm_design,
            "roles": r.roles,
            "perturbation_intensity": r.perturbation_intensity,
            "agents_per_problem": r.agents_per_problem,
            "swarm_agents": r.swarm_agents,
            "oracle_rounds": r.oracle_rounds,
            "cost_usd": r.cost_usd,
            "duration_s": r.duration_s,
        }
        for r in runs
    ]


@router.get("/api/benchmarks/{run_id}")
async def get_run(run_id: str):
    """Get a single run with task details (JSON)."""
    runs = scan_all_runs(BASE_DIR)
    run = next((r for r in runs if r.run_id == run_id), None)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    return {
        "run_id": run.run_id,
        "model": run.model,
        "total": run.total,
        "passed": run.passed,
        "failed": run.failed,
        "pass_rate": run.pass_rate,
        "solver": run.solver,
        "swarm_design": run.swarm_design,
        "roles": run.roles,
        "perturbation_intensity": run.perturbation_intensity,
        "agents_per_problem": run.agents_per_problem,
        "swarm_agents": run.swarm_agents,
        "oracle_rounds": run.oracle_rounds,
        "cost_usd": run.cost_usd,
        "duration_s": run.duration_s,
        "tasks": [
            {
                "instance_id": t.instance_id,
                "resolved": t.resolved,
                "patch_applied": t.patch_applied,
                "patch_exists": t.patch_exists,
                "tests_status": t.tests_status,
            }
            for t in run.tasks
        ],
    }


@router.get("/api/benchmarks/{run_id}/{instance_id}")
async def get_task(run_id: str, instance_id: str):
    """Get task detail (JSON)."""
    task = get_task_detail(run_id, instance_id, BASE_DIR)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "instance_id": task.instance_id,
        "resolved": task.resolved,
        "patch_applied": task.patch_applied,
        "patch_exists": task.patch_exists,
        "tests_status": task.tests_status,
        "has_test_output": task.test_output_path is not None,
        "has_agent_logs": bool(get_agent_logs(run_id, instance_id, BASE_DIR)),
    }


@router.get("/api/benchmarks/{run_id}/{instance_id}/test-output")
async def get_task_test_output(run_id: str, instance_id: str):
    """Get raw test output for a task."""
    output = get_test_output(run_id, instance_id, BASE_DIR)
    if output is None:
        raise HTTPException(status_code=404, detail="Test output not found")
    return {"test_output": output}


@router.get("/api/benchmarks/{run_id}/{instance_id}/agent-logs")
async def get_task_agent_logs(run_id: str, instance_id: str):
    """Get agent chat logs for a task."""
    logs = get_agent_logs(run_id, instance_id, BASE_DIR)
    return {"messages": logs}


@router.post("/api/benchmarks/{run_id}/{instance_id}/summary")
async def generate_ai_summary(run_id: str, instance_id: str):
    """
    Generate an AI summary of what tests failed and why.

    Reads test_output.txt and report.json, sends to Claude for summarization.
    Caches the result to disk so subsequent calls return instantly.
    """
    # Check for cached summary first
    cached = get_ai_summary(run_id, instance_id, BASE_DIR)
    if cached:
        return {"summary": cached}

    # Get the test data
    task = get_task_detail(run_id, instance_id, BASE_DIR)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    test_output = get_test_output(run_id, instance_id, BASE_DIR)

    # Build context for the AI
    f2p = task.tests_status.get("FAIL_TO_PASS", {})
    f2p_failures = f2p.get("failure", [])
    f2p_successes = f2p.get("success", [])
    p2p = task.tests_status.get("PASS_TO_PASS", {})
    p2p_failures = p2p.get("failure", [])

    context_parts = [
        f"Instance: {instance_id}",
        f"Resolved: {task.resolved}",
        f"Patch applied: {task.patch_applied}",
        "",
        "FAIL_TO_PASS tests that succeeded (fixed): " + str(len(f2p_successes)),
        "FAIL_TO_PASS tests that still fail: " + str(len(f2p_failures)),
    ]
    if f2p_failures:
        context_parts.append("Still failing tests:")
        for t in f2p_failures:
            context_parts.append(f"  - {t}")
    if p2p_failures:
        context_parts.append(f"\nPASS_TO_PASS regressions ({len(p2p_failures)}):")
        for t in p2p_failures:
            context_parts.append(f"  - {t}")

    if test_output:
        # Take last 8000 chars of test output (most relevant part)
        truncated = test_output[-8000:] if len(test_output) > 8000 else test_output
        context_parts.append("\n--- Test Output (tail) ---")
        context_parts.append(truncated)

    context = "\n".join(context_parts)

    # Try to generate summary with Claude
    try:
        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-sonnet-4-5-20250514",
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Summarize what tests failed and why based on this SWE-bench evaluation output. "
                        "Be concise (3-5 sentences). Focus on: which tests still fail, what error messages "
                        "appear, and what the likely root cause is.\n\n"
                        f"{context}"
                    ),
                }
            ],
        )
        summary = response.content[0].text
    except Exception as e:
        logger.warning(f"AI summary generation failed: {e}")
        # Fall back to a simple programmatic summary
        summary = _build_fallback_summary(task, f2p_failures, p2p_failures)

    # Cache the summary
    save_ai_summary(run_id, instance_id, summary, BASE_DIR)
    return {"summary": summary}


def _build_fallback_summary(
    task, f2p_failures: list[str], p2p_failures: list[str]
) -> str:
    """Build a simple summary when AI is not available."""
    parts = []
    if task.resolved:
        parts.append("This task was resolved successfully.")
    else:
        if not task.patch_applied:
            parts.append("The patch could not be applied to the repository.")
        if f2p_failures:
            parts.append(
                f"{len(f2p_failures)} test(s) that should have been fixed are still failing: "
                + ", ".join(f2p_failures[:3])
                + ("..." if len(f2p_failures) > 3 else "")
            )
        if p2p_failures:
            parts.append(
                f"{len(p2p_failures)} previously passing test(s) now fail (regressions): "
                + ", ".join(p2p_failures[:3])
                + ("..." if len(p2p_failures) > 3 else "")
            )
        if not f2p_failures and not p2p_failures and task.patch_applied:
            parts.append(
                "Patch was applied but the task is not marked as resolved. "
                "Check the test output for details."
            )
    return " ".join(parts) if parts else "No summary available."
