"""
Filesystem scanner for SWE-bench evaluation runs.

Discovers benchmark runs by walking logs/run_evaluation/ and correlates
with results/ and root-level summary JSONs for metadata.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TaskResult:
    """Result of a single SWE-bench task within a benchmark run."""

    instance_id: str
    resolved: bool
    patch_applied: bool
    patch_exists: bool
    tests_status: dict[str, dict[str, list[str]]]
    test_output_path: str | None = None
    run_instance_log_path: str | None = None
    # Per-task metadata from raw_results.json
    duration_s: float | None = None
    num_turns: int | None = None
    cost_usd: float | None = None
    roles: list[str] = field(default_factory=list)


@dataclass
class AgentResult:
    """Per-agent metadata from raw_results.json."""

    agent_id: str
    instance_id: str
    model_patch: str = ""
    duration_s: float = 0.0
    num_turns: int = 0
    cost_usd: float = 0.0
    swarm_agents: int = 0
    perturbation_intensity: float = 0.0
    swarm_design: str = ""
    roles: list[str] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class BenchmarkRun:
    """A complete benchmark evaluation run."""

    run_id: str
    model: str
    tasks: list[TaskResult]
    total: int = 0
    passed: int = 0
    failed: int = 0
    # Aggregated metadata from raw_results
    swarm_design: str | None = None
    roles: list[str] | None = None
    perturbation_intensity: float | None = None
    solver: str | None = None
    cost_usd: float | None = None
    duration_s: float | None = None
    # Config details
    agents_per_problem: int | None = None
    max_agent_turns: int | None = None
    swarm_agents: int | None = None
    oracle_rounds: int | None = None
    dataset: str | None = None

    def __post_init__(self):
        self.total = len(self.tasks)
        self.passed = sum(1 for t in self.tasks if t.resolved)
        self.failed = self.total - self.passed

    @property
    def pass_rate(self) -> float:
        return (self.passed / self.total * 100) if self.total > 0 else 0.0


def scan_all_runs(base_dir: Path | None = None) -> list[BenchmarkRun]:
    """
    Scan logs/run_evaluation/ to discover all benchmark runs.

    Each subdirectory of run_evaluation/ is a run_id. Under each run_id,
    there's a model directory, then instance_id directories with report.json.

    Returns list of BenchmarkRun sorted by run_id.
    """
    if base_dir is None:
        base_dir = Path.cwd()

    eval_dir = base_dir / "logs" / "run_evaluation"
    if not eval_dir.exists():
        logger.warning(f"Evaluation directory not found: {eval_dir}")
        return []

    runs = []
    for run_dir in sorted(eval_dir.iterdir()):
        if not run_dir.is_dir():
            continue

        run_id = run_dir.name
        run = _scan_single_run(run_dir, run_id, base_dir)
        if run:
            runs.append(run)

    return runs


def _scan_single_run(
    run_dir: Path, run_id: str, base_dir: Path
) -> BenchmarkRun | None:
    """Scan a single run directory and build a BenchmarkRun."""
    tasks: list[TaskResult] = []
    model = ""

    # Structure: run_dir/<model>/<instance_id>/report.json
    for model_dir in run_dir.iterdir():
        if not model_dir.is_dir():
            continue
        model = model_dir.name

        for instance_dir in sorted(model_dir.iterdir()):
            if not instance_dir.is_dir():
                continue

            report_file = instance_dir / "report.json"
            if not report_file.exists():
                continue

            task = _parse_report(report_file, instance_dir)
            if task:
                tasks.append(task)

    if not tasks:
        return None

    run = BenchmarkRun(run_id=run_id, model=model, tasks=tasks)

    # Try to load metadata from raw_results or summary JSONs
    _enrich_run_metadata(run, base_dir)

    return run


def _parse_report(report_file: Path, instance_dir: Path) -> TaskResult | None:
    """Parse a report.json file into a TaskResult."""
    try:
        with open(report_file) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to parse {report_file}: {e}")
        return None

    if not isinstance(data, dict) or not data:
        return None

    # report.json has one key: the instance_id
    instance_id = next(iter(data))
    status = data[instance_id]

    test_output = instance_dir / "test_output.txt"
    run_log = instance_dir / "run_instance.log"

    return TaskResult(
        instance_id=instance_id,
        resolved=status.get("resolved", False),
        patch_applied=status.get("patch_successfully_applied", False),
        patch_exists=status.get("patch_exists", False),
        tests_status=status.get("tests_status", {}),
        test_output_path=str(test_output) if test_output.exists() else None,
        run_instance_log_path=str(run_log) if run_log.exists() else None,
    )


def _enrich_run_metadata(run: BenchmarkRun, base_dir: Path) -> None:
    """
    Try to find matching raw_results.json or summary JSON to add metadata.

    Looks in results/ directories and root-level kekule-*.json files.
    """
    # Check root-level summary JSONs (e.g., kekule-swarm-claude-opus-4-5.eval-ansh-perturbation-high.json)
    for summary_file in base_dir.glob("kekule-*.json"):
        if run.run_id in summary_file.stem:
            try:
                with open(summary_file) as f:
                    data = json.load(f)
                # These files have schema_version, resolved_ids, etc.
                # but not much agent metadata
            except Exception:
                pass

    # Check results/ directories for raw_results.json
    results_dir = base_dir / "results"
    if not results_dir.exists():
        return

    for iter_dir in results_dir.rglob("iteration_*"):
        raw_file = iter_dir / "raw_results.json"
        if not raw_file.exists():
            continue

        try:
            with open(raw_file) as f:
                raw_results = json.load(f)
        except Exception:
            continue

        if not isinstance(raw_results, list) or not raw_results:
            continue

        # Check if this raw_results matches our run by looking at instance_ids
        raw_ids = {r.get("instance_id") for r in raw_results}
        run_ids = {t.instance_id for t in run.tasks}

        if not raw_ids.intersection(run_ids):
            continue

        # Check if model names match
        raw_model = raw_results[0].get("model_name_or_path", "")
        if raw_model and raw_model != run.model:
            continue

        # Extract metadata from first result
        first = raw_results[0]
        run.swarm_design = first.get("swarm_design")
        run.roles = first.get("roles")
        run.perturbation_intensity = first.get("perturbation_intensity")
        run.swarm_agents = first.get("swarm_agents")
        run.oracle_rounds = first.get("oracle_rounds")

        # Derive solver name from model_name_or_path (e.g. "kekule-oracle-swarm-claude-opus-4-5")
        model_path = first.get("model_name_or_path", "")
        if model_path.startswith("kekule-"):
            parts = model_path.split("-")
            # Find where the model name starts (claude-...)
            for i, p in enumerate(parts):
                if p == "claude" and i > 1:
                    run.solver = "-".join(parts[1:i])
                    break

        # Count distinct agents per instance to infer agents_per_problem
        instance_counts: dict[str, int] = {}
        for r in raw_results:
            iid = r.get("instance_id", "")
            instance_counts[iid] = instance_counts.get(iid, 0) + 1
        if instance_counts:
            run.agents_per_problem = max(instance_counts.values())

        # Build lookup for per-task metadata
        raw_by_id = {r.get("instance_id"): r for r in raw_results}

        # Enrich per-task metadata
        for task in run.tasks:
            raw = raw_by_id.get(task.instance_id)
            if raw:
                task.duration_s = raw.get("duration_s")
                task.num_turns = raw.get("num_turns")
                task.cost_usd = raw.get("cost_usd")
                task.roles = raw.get("roles", [])

        # Aggregate cost and duration
        total_cost = sum(r.get("cost_usd", 0) for r in raw_results)
        total_duration = sum(r.get("duration_s", 0) for r in raw_results)
        if total_cost > 0:
            run.cost_usd = total_cost
        if total_duration > 0:
            run.duration_s = total_duration

        break


def get_task_detail(
    run_id: str, instance_id: str, base_dir: Path | None = None
) -> TaskResult | None:
    """Get detailed TaskResult for a specific run + instance."""
    if base_dir is None:
        base_dir = Path.cwd()

    eval_dir = base_dir / "logs" / "run_evaluation" / run_id
    if not eval_dir.exists():
        return None

    for model_dir in eval_dir.iterdir():
        if not model_dir.is_dir():
            continue
        instance_dir = model_dir / instance_id
        if instance_dir.exists():
            report_file = instance_dir / "report.json"
            if report_file.exists():
                return _parse_report(report_file, instance_dir)

    return None


def get_test_output(
    run_id: str, instance_id: str, base_dir: Path | None = None
) -> str | None:
    """Read the raw test_output.txt for a task."""
    if base_dir is None:
        base_dir = Path.cwd()

    eval_dir = base_dir / "logs" / "run_evaluation" / run_id
    if not eval_dir.exists():
        return None

    for model_dir in eval_dir.iterdir():
        if not model_dir.is_dir():
            continue
        test_output = model_dir / instance_id / "test_output.txt"
        if test_output.exists():
            return test_output.read_text()

    return None


def get_agent_logs(
    run_id: str, instance_id: str, base_dir: Path | None = None
) -> list[dict[str, Any]]:
    """
    Find agent chat logs (messages) for a specific task from raw_results.json.

    Returns the messages list from the matching agent result entry.
    """
    if base_dir is None:
        base_dir = Path.cwd()

    results_dir = base_dir / "results"
    if not results_dir.exists():
        return []

    for iter_dir in results_dir.rglob("iteration_*"):
        raw_file = iter_dir / "raw_results.json"
        if not raw_file.exists():
            continue

        try:
            with open(raw_file) as f:
                raw_results = json.load(f)
        except Exception:
            continue

        for result in raw_results:
            if result.get("instance_id") == instance_id:
                return result.get("messages", [])

    return []


def get_ai_summary(
    run_id: str, instance_id: str, base_dir: Path | None = None
) -> str | None:
    """Read cached AI summary if it exists."""
    if base_dir is None:
        base_dir = Path.cwd()

    eval_dir = base_dir / "logs" / "run_evaluation" / run_id
    if not eval_dir.exists():
        return None

    for model_dir in eval_dir.iterdir():
        if not model_dir.is_dir():
            continue
        summary_file = model_dir / instance_id / "ai_summary.json"
        if summary_file.exists():
            try:
                with open(summary_file) as f:
                    data = json.load(f)
                return data.get("summary", "")
            except Exception:
                pass

    return None


def save_ai_summary(
    run_id: str, instance_id: str, summary: str, base_dir: Path | None = None
) -> None:
    """Cache an AI summary to disk."""
    if base_dir is None:
        base_dir = Path.cwd()

    eval_dir = base_dir / "logs" / "run_evaluation" / run_id
    if not eval_dir.exists():
        return

    for model_dir in eval_dir.iterdir():
        if not model_dir.is_dir():
            continue
        instance_dir = model_dir / instance_id
        if instance_dir.exists():
            summary_file = instance_dir / "ai_summary.json"
            with open(summary_file, "w") as f:
                json.dump({"summary": summary}, f, indent=2)
            return


def get_fault_analysis(
    instance_id: str, base_dir: Path | None = None
) -> dict[str, Any] | None:
    """
    Find fault analysis for a task from coordinator_output.json files.

    The coordinator's 'analysis' field contains per-task failure pattern
    analysis. We search all epoch directories for analysis mentioning
    the given instance_id and return the most relevant one.

    Returns dict with 'analysis' (full text) and 'epoch' keys, or None.
    """
    if base_dir is None:
        base_dir = Path.cwd()

    results_dir = base_dir / "results"
    if not results_dir.exists():
        return None

    # Search epoch directories for coordinator output
    best: dict[str, Any] | None = None
    for epoch_dir in sorted(results_dir.iterdir()):
        if not epoch_dir.is_dir():
            continue

        coord_file = epoch_dir / "coordinator_output.json"
        if not coord_file.exists():
            continue

        try:
            with open(coord_file) as f:
                data = json.load(f)
        except Exception:
            continue

        analysis = data.get("analysis", "")
        if not analysis:
            continue

        # Extract the instance-specific short ID for matching
        # e.g. "django__django-14534" -> look for "django-14534" in analysis
        short_id = instance_id.split("__")[-1] if "__" in instance_id else instance_id
        if short_id in analysis:
            best = {
                "analysis": analysis,
                "epoch": epoch_dir.name,
                "train_score": data.get("train_score"),
                "test_score": data.get("test_score"),
                "lessons": data.get("lessons_text", ""),
            }

    return best


def get_epoch_swarm_data(
    epoch: int, instance_id: str, base_dir: Path | None = None
) -> dict[str, Any]:
    """
    Get swarm data for a specific epoch + task.

    Returns dict with 'broadcast', 'agents' (list of agent findings),
    and 'roles' (agent-role pairs).
    """
    import re

    if base_dir is None:
        base_dir = Path.cwd()

    short_id = instance_id.split("__")[-1] if "__" in instance_id else instance_id
    prefix = f"epoch{epoch}-{short_id}"

    # Find the matching workspace
    ledger_path: Path | None = None
    for ws_root in ["workspaces", "workspaces-swarm"]:
        ws_dir = base_dir / ws_root
        if not ws_dir.exists():
            continue
        for workspace in ws_dir.iterdir():
            if workspace.is_dir() and workspace.name == prefix:
                candidate = workspace / "repo" / "swarm_ledger"
                if candidate.exists():
                    ledger_path = candidate
                    break
        if ledger_path:
            break

    result: dict[str, Any] = {
        "broadcast": None,
        "agents": [],
        "roles": [],
    }

    if ledger_path is None:
        return result

    # Read BROADCAST.md
    broadcast_file = ledger_path / "BROADCAST.md"
    if broadcast_file.exists():
        content = broadcast_file.read_text().strip()
        if content:
            result["broadcast"] = content

    # Read per-agent findings
    for agent_dir in sorted(ledger_path.iterdir()):
        if not agent_dir.is_dir() or not agent_dir.name.startswith("agent-"):
            continue

        agent_name = agent_dir.name
        findings = ""
        status = ""
        role = ""

        findings_file = agent_dir / "findings.md"
        if findings_file.exists():
            content = findings_file.read_text().strip()
            if content and len(content) > 30:
                findings = content
                role_match = re.search(r"\((\w+)\)", content.split("\n")[0])
                if role_match:
                    role = role_match.group(1)

        status_file = agent_dir / "status.md"
        if status_file.exists():
            status = status_file.read_text().strip()

        result["agents"].append({
            "agent": agent_name,
            "role": role,
            "status": status,
            "findings": findings,
        })

    # Extract roles from broadcast
    if result["broadcast"]:
        agent_roles: dict[str, set[str]] = {}
        for match in re.finditer(r"agent-(\d+) \(([^)]+)\)", result["broadcast"]):
            agent_roles.setdefault(match.group(1), set()).add(match.group(2))
        for agent_num in sorted(agent_roles.keys(), key=int):
            for role in sorted(agent_roles[agent_num]):
                result["roles"].append({"agent": f"agent-{agent_num}", "role": role})

    return result


def get_swarm_roles(
    instance_id: str, base_dir: Path | None = None
) -> list[dict[str, str]]:
    """
    Extract agent role assignments for a task.

    Pulls from raw_results.json (roles list) and BROADCAST.md
    (agent-N (role) patterns) to build a list of {agent, role} dicts.
    """
    import re

    if base_dir is None:
        base_dir = Path.cwd()

    # First try raw_results for the roles list + swarm_design
    results_dir = base_dir / "results"
    roles_list: list[str] = []
    swarm_design = ""

    if results_dir.exists():
        for raw_file in results_dir.rglob("raw_results.json"):
            try:
                with open(raw_file) as f:
                    data = json.load(f)
            except Exception:
                continue
            for r in data:
                if r.get("instance_id") == instance_id:
                    roles_list = r.get("roles", [])
                    swarm_design = r.get("swarm_design", "")
                    break
            if roles_list:
                break

    # Also parse BROADCAST.md for agent-N (role) patterns
    broadcast = get_swarm_broadcast(instance_id, base_dir)
    agent_roles: dict[str, set[str]] = {}
    if broadcast:
        for match in re.finditer(r"agent-(\d+) \(([^)]+)\)", broadcast):
            agent_num = match.group(1)
            role = match.group(2)
            agent_roles.setdefault(agent_num, set()).add(role)

    # Build result list
    result: list[dict[str, str]] = []
    if agent_roles:
        for agent_num in sorted(agent_roles.keys(), key=int):
            for role in sorted(agent_roles[agent_num]):
                result.append({"agent": f"agent-{agent_num}", "role": role})
    elif roles_list:
        for i, role in enumerate(roles_list):
            result.append({"agent": f"agent-{i}", "role": role})

    return result


def get_agent_findings(
    instance_id: str, base_dir: Path | None = None
) -> list[dict[str, str]]:
    """
    Collect per-agent findings and status from swarm_ledger/agent-N/ directories.

    Returns list of dicts with 'agent', 'role', 'status', 'findings' keys.
    """
    import re

    if base_dir is None:
        base_dir = Path.cwd()

    short_id = instance_id.split("__")[-1] if "__" in instance_id else instance_id

    best_workspace: Path | None = None
    for ws_root in ["workspaces", "workspaces-swarm", "workspaces-single"]:
        ws_dir = base_dir / ws_root
        if not ws_dir.exists():
            continue
        for workspace in sorted(ws_dir.iterdir()):
            if not workspace.is_dir() or short_id not in workspace.name:
                continue
            ledger = workspace / "repo" / "swarm_ledger"
            if ledger.exists():
                best_workspace = ledger

    if best_workspace is None:
        return []

    results: list[dict[str, str]] = []
    for agent_dir in sorted(best_workspace.iterdir()):
        if not agent_dir.is_dir() or not agent_dir.name.startswith("agent-"):
            continue

        agent_name = agent_dir.name
        findings = ""
        status = ""

        findings_file = agent_dir / "findings.md"
        if findings_file.exists():
            content = findings_file.read_text().strip()
            if content and len(content) > 30:
                findings = content

        status_file = agent_dir / "status.md"
        if status_file.exists():
            status = status_file.read_text().strip()

        # Extract role from findings header if present
        role = ""
        if findings:
            role_match = re.search(r"\((\w+)\)", findings.split("\n")[0])
            if role_match:
                role = role_match.group(1)

        if findings or status:
            results.append({
                "agent": agent_name,
                "role": role,
                "status": status,
                "findings": findings,
            })

    return results


def get_swarm_broadcast(
    instance_id: str, base_dir: Path | None = None
) -> str | None:
    """
    Find the BROADCAST.md swarm communication log for a task.

    Searches workspaces/ for directories matching the instance_id
    and returns the BROADCAST.md content.

    Returns the broadcast log text, or None if not found.
    """
    if base_dir is None:
        base_dir = Path.cwd()

    # Extract short task id: "django__django-14534" -> "django-14534"
    short_id = instance_id.split("__")[-1] if "__" in instance_id else instance_id

    # Search all workspace directories for matching BROADCAST.md files
    # Prefer epoch workspaces over iteration workspaces
    broadcasts: list[tuple[str, str]] = []

    for ws_root in ["workspaces", "workspaces-swarm", "workspaces-single"]:
        ws_dir = base_dir / ws_root
        if not ws_dir.exists():
            continue

        for workspace in sorted(ws_dir.iterdir()):
            if not workspace.is_dir():
                continue
            if short_id not in workspace.name:
                continue

            broadcast = workspace / "repo" / "swarm_ledger" / "BROADCAST.md"
            if broadcast.exists():
                try:
                    content = broadcast.read_text()
                    if content.strip():
                        broadcasts.append((workspace.name, content))
                except Exception:
                    pass

    if not broadcasts:
        return None

    # If multiple broadcasts, return the most recent epoch or the longest
    # Prefer epoch dirs (epoch0-, epoch1-) over iter dirs (iter0-)
    epoch_broadcasts = [(n, c) for n, c in broadcasts if n.startswith("epoch")]
    if epoch_broadcasts:
        # Return the latest epoch
        return epoch_broadcasts[-1][1]

    return broadcasts[-1][1]
