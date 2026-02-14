"""
Application state for the Oracle Dashboard backend.

Holds live references to SwarmBus and BeadsTracker, plus
in-memory stores for projects, rules, waypoints, oracle results, and overrides.
Persists to JSON files in a configurable data directory.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from kekule.benchmarks.swarm_bus import SwarmBus
from kekule.benchmarks.swarm_beads import BeadsTracker

from .models import (
    Override,
    OracleResult,
    Project,
    Rule,
    Waypoint,
)

logger = logging.getLogger(__name__)


class AppState:
    """
    Central application state shared across all route handlers.

    Holds live SwarmBus/BeadsTracker when a swarm is running, plus
    persistent stores for projects, rules, waypoints, oracle results,
    and overrides.
    """

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or Path(__file__).parent / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Live swarm references (set via attach_bus / attach_tracker)
        self.bus: SwarmBus | None = None
        self.tracker: BeadsTracker | None = None

        # Persistent stores
        self.projects: dict[str, Project] = {}
        self.rules: dict[str, Rule] = {}
        self.waypoints: dict[str, Waypoint] = {}
        self.oracle_results: dict[str, list[OracleResult]] = {}  # waypoint_id -> results
        self.overrides: list[Override] = []

        # Load persisted data
        self._load()

    # ----- Swarm integration -------------------------------------------------

    def attach_bus(self, bus: SwarmBus) -> None:
        """Attach a live SwarmBus instance for real-time monitoring."""
        self.bus = bus
        logger.info("SwarmBus attached to AppState")

    def attach_tracker(self, tracker: BeadsTracker) -> None:
        """Attach a live BeadsTracker instance for task tracking."""
        self.tracker = tracker
        logger.info("BeadsTracker attached to AppState")

    @property
    def bus_connected(self) -> bool:
        return self.bus is not None

    @property
    def tracker_connected(self) -> bool:
        return self.tracker is not None

    # ----- Projects CRUD -----------------------------------------------------

    def add_project(self, project: Project) -> Project:
        self.projects[project.id] = project
        self._save_projects()
        return project

    def update_project(self, project_id: str, updates: dict[str, Any]) -> Project | None:
        project = self.projects.get(project_id)
        if project is None:
            return None
        for key, value in updates.items():
            if value is not None and hasattr(project, key):
                setattr(project, key, value)
        self.projects[project_id] = project
        self._save_projects()
        return project

    def delete_project(self, project_id: str) -> bool:
        if project_id in self.projects:
            del self.projects[project_id]
            self._save_projects()
            return True
        return False

    def get_project(self, project_id: str) -> Project | None:
        return self.projects.get(project_id)

    def list_projects(self) -> list[Project]:
        return list(self.projects.values())

    # ----- Rules CRUD ---------------------------------------------------------

    def add_rule(self, rule: Rule) -> Rule:
        self.rules[rule.id] = rule
        self._save_rules()
        return rule

    def update_rule(self, rule_id: str, updates: dict[str, Any]) -> Rule | None:
        rule = self.rules.get(rule_id)
        if rule is None:
            return None
        for key, value in updates.items():
            if value is not None and hasattr(rule, key):
                setattr(rule, key, value)
        self.rules[rule_id] = rule
        self._save_rules()
        return rule

    def delete_rule(self, rule_id: str) -> bool:
        if rule_id in self.rules:
            del self.rules[rule_id]
            self._save_rules()
            return True
        return False

    def get_rule(self, rule_id: str) -> Rule | None:
        return self.rules.get(rule_id)

    def list_rules(self, project_id: str | None = None) -> list[Rule]:
        rules = list(self.rules.values())
        if project_id:
            rules = [r for r in rules if r.project_id == project_id]
        return rules

    # ----- Waypoints CRUD -----------------------------------------------------

    def add_waypoint(self, waypoint: Waypoint) -> Waypoint:
        self.waypoints[waypoint.id] = waypoint
        self._save_waypoints()
        return waypoint

    def update_waypoint(self, waypoint_id: str, updates: dict[str, Any]) -> Waypoint | None:
        wp = self.waypoints.get(waypoint_id)
        if wp is None:
            return None
        for key, value in updates.items():
            if value is not None and hasattr(wp, key):
                setattr(wp, key, value)
        self.waypoints[waypoint_id] = wp
        self._save_waypoints()
        return wp

    def get_waypoint(self, waypoint_id: str) -> Waypoint | None:
        return self.waypoints.get(waypoint_id)

    def list_waypoints(self, project_id: str | None = None) -> list[Waypoint]:
        waypoints = list(self.waypoints.values())
        if project_id:
            waypoints = [w for w in waypoints if w.project_id == project_id]
        return waypoints

    # ----- Oracle results -----------------------------------------------------

    def add_oracle_result(self, result: OracleResult) -> OracleResult:
        if result.waypoint_id not in self.oracle_results:
            self.oracle_results[result.waypoint_id] = []
        self.oracle_results[result.waypoint_id].append(result)
        self._save_oracle_results()
        return result

    def get_oracle_results(self, waypoint_id: str) -> list[OracleResult]:
        return self.oracle_results.get(waypoint_id, [])

    # ----- Overrides ----------------------------------------------------------

    def add_override(self, override: Override) -> Override:
        self.overrides.append(override)
        self._save_overrides()
        return override

    def list_overrides(self) -> list[Override]:
        return list(self.overrides)

    # ----- Swarm reads (from live bus) ----------------------------------------

    def get_agent_statuses(self) -> list[dict[str, Any]]:
        """Read current agent statuses from the live SwarmBus."""
        if not self.bus_connected:
            return []

        bus = self.bus
        agents = []
        for agent_num in range(bus._num_agents):
            agents.append({
                "agent_num": agent_num,
                "role": bus._roles.get(agent_num, f"agent-{agent_num}"),
                "status": bus._statuses.get(agent_num, "unknown"),
                "current_file": bus._current_files.get(agent_num, ""),
            })
        return agents

    def get_swarm_messages(self, since: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        """Read messages from the live SwarmBus, optionally filtering by cursor."""
        if not self.bus_connected:
            return []

        bus = self.bus
        messages = [
            {
                "seq": m.seq,
                "agent_num": m.agent_num,
                "role": m.role,
                "category": m.category,
                "content": m.content,
                "timestamp": m.timestamp,
            }
            for m in bus._messages
            if m.seq > since
        ]
        return messages[-limit:]

    # ----- Persistence --------------------------------------------------------

    def _save_projects(self) -> None:
        path = self.data_dir / "projects.json"
        data = {pid: p.model_dump(mode="json") for pid, p in self.projects.items()}
        path.write_text(json.dumps(data, indent=2, default=str))

    def _save_rules(self) -> None:
        path = self.data_dir / "rules.json"
        data = {rid: r.model_dump(mode="json") for rid, r in self.rules.items()}
        path.write_text(json.dumps(data, indent=2, default=str))

    def _save_waypoints(self) -> None:
        path = self.data_dir / "waypoints.json"
        data = {wid: w.model_dump(mode="json") for wid, w in self.waypoints.items()}
        path.write_text(json.dumps(data, indent=2, default=str))

    def _save_oracle_results(self) -> None:
        path = self.data_dir / "oracle_results.json"
        data = {
            wid: [r.model_dump(mode="json") for r in results]
            for wid, results in self.oracle_results.items()
        }
        path.write_text(json.dumps(data, indent=2, default=str))

    def _save_overrides(self) -> None:
        path = self.data_dir / "overrides.json"
        data = [o.model_dump(mode="json") for o in self.overrides]
        path.write_text(json.dumps(data, indent=2, default=str))

    def _load(self) -> None:
        """Load persisted data from JSON files."""
        self._load_projects()
        self._load_rules()
        self._load_waypoints()
        self._load_oracle_results()
        self._load_overrides()

    def _load_projects(self) -> None:
        path = self.data_dir / "projects.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            self.projects = {pid: Project(**pdata) for pid, pdata in data.items()}
            logger.info(f"Loaded {len(self.projects)} projects from {path}")
        except Exception as e:
            logger.warning(f"Failed to load projects: {e}")

    def _load_rules(self) -> None:
        path = self.data_dir / "rules.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            self.rules = {rid: Rule(**rdata) for rid, rdata in data.items()}
            logger.info(f"Loaded {len(self.rules)} rules from {path}")
        except Exception as e:
            logger.warning(f"Failed to load rules: {e}")

    def _load_waypoints(self) -> None:
        path = self.data_dir / "waypoints.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            self.waypoints = {wid: Waypoint(**wdata) for wid, wdata in data.items()}
            logger.info(f"Loaded {len(self.waypoints)} waypoints from {path}")
        except Exception as e:
            logger.warning(f"Failed to load waypoints: {e}")

    def _load_oracle_results(self) -> None:
        path = self.data_dir / "oracle_results.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            self.oracle_results = {
                wid: [OracleResult(**r) for r in results]
                for wid, results in data.items()
            }
            logger.info(f"Loaded oracle results for {len(self.oracle_results)} waypoints")
        except Exception as e:
            logger.warning(f"Failed to load oracle results: {e}")

    def _load_overrides(self) -> None:
        path = self.data_dir / "overrides.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            self.overrides = [Override(**o) for o in data]
            logger.info(f"Loaded {len(self.overrides)} overrides")
        except Exception as e:
            logger.warning(f"Failed to load overrides: {e}")
