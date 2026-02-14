"""
Centralized configuration for the SWE-bench harness.

All experiment parameters and model settings live here.
Override via CLI arguments or environment variables.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class HarnessConfig:
    # -- Model ----------------------------------------------------------------
    model: str = "claude-opus-4-5"

    # -- Experiment parameters ------------------------------------------------
    experiment_name: str = ""
    solver: str = "default"
    agents_per_problem: int = 3
    num_problems: int = 3
    num_iterations: int = 3
    max_agent_turns: int = 100
    max_parallel: int = 6
    start_iteration: int = 0

    # -- Perturbation policy --------------------------------------------------
    perturbation_mode: str = "off"
    perturbation_intensity: float = 0.0
    perturbation_target_tools: list[str] = field(default_factory=lambda: ["Bash"])
    perturbation_seed: int = 0
    perturbation_phase_scope: str = "swarm_phase1"

    # -- ChatOverflow (optional) ----------------------------------------------
    chatoverflow_api_url: str = "https://www.chatoverflow.dev"
    enable_chatoverflow: bool = False

    # -- LangFuse (optional, configure via env vars) --------------------------
    langfuse_secret_key: str = ""
    langfuse_public_key: str = ""
    langfuse_base_url: str = ""

    # -- Paths ----------------------------------------------------------------
    base_dir: Path = field(default_factory=lambda: Path.cwd())
    results_dir: Path = field(default_factory=lambda: Path.cwd() / "results")
    workspaces_dir: Path = field(default_factory=lambda: Path.cwd() / "workspaces")
    repo_cache_dir: Path = field(
        default_factory=lambda: Path("/tmp/swe-bench-repo-cache")
    )

    # -- SWE-bench task IDs (override via CLI) --------------------------------
    # These are medium/hard problems selected for multi-agent collaboration benefit.
    # Set to empty list to use task_selector auto-pick.
    task_ids: list[str] = field(default_factory=list)
    repos: list[str] = field(default_factory=list)
    task_file: str = ""

    # -- Claude settings (loaded from ~/.claude/settings.json) ----------------
    claude_settings_path: Path = field(
        default_factory=lambda: Path.home() / ".claude" / "settings.json"
    )

    def load_claude_settings(self) -> dict:
        """Load Claude settings from ~/.claude/settings.json for API proxy config."""
        if self.claude_settings_path.exists():
            with open(self.claude_settings_path) as f:
                return json.load(f)
        return {}

    def get_claude_env(self) -> dict[str, str]:
        """Extract environment variables from Claude settings."""
        settings = self.load_claude_settings()
        return settings.get("env", {})

    @property
    def langfuse_enabled(self) -> bool:
        """Check if LangFuse tracing is configured."""
        return bool(self.langfuse_secret_key and self.langfuse_public_key and self.langfuse_base_url)

    @classmethod
    def from_args(cls, args) -> "HarnessConfig":
        """Create config from argparse namespace."""
        config = cls()
        if hasattr(args, "experiment_name") and args.experiment_name:
            config.experiment_name = args.experiment_name
        if hasattr(args, "solver") and args.solver:
            config.solver = args.solver
        if hasattr(args, "model") and args.model:
            config.model = args.model
        if hasattr(args, "problems") and args.problems:
            config.num_problems = args.problems
        if hasattr(args, "agents_per_problem") and args.agents_per_problem:
            config.agents_per_problem = args.agents_per_problem
        if hasattr(args, "iterations") and args.iterations:
            config.num_iterations = args.iterations
        if hasattr(args, "task_ids") and args.task_ids:
            config.task_ids = args.task_ids
        if hasattr(args, "repos") and args.repos:
            config.repos = args.repos
        if hasattr(args, "task_file") and args.task_file:
            config.task_file = args.task_file
        if hasattr(args, "chatoverflow_url") and args.chatoverflow_url:
            config.chatoverflow_api_url = args.chatoverflow_url
        if hasattr(args, "enable_chatoverflow") and args.enable_chatoverflow:
            config.enable_chatoverflow = True
        if hasattr(args, "max_turns") and args.max_turns:
            config.max_agent_turns = args.max_turns
        if hasattr(args, "max_parallel") and args.max_parallel:
            config.max_parallel = args.max_parallel
        if hasattr(args, "start_iteration") and args.start_iteration is not None:
            config.start_iteration = args.start_iteration
        if hasattr(args, "perturbation_mode") and args.perturbation_mode:
            config.perturbation_mode = args.perturbation_mode
        if hasattr(args, "perturbation_intensity") and args.perturbation_intensity is not None:
            config.perturbation_intensity = args.perturbation_intensity
        if hasattr(args, "perturbation_target_tools") and args.perturbation_target_tools:
            config.perturbation_target_tools = args.perturbation_target_tools
        if hasattr(args, "perturbation_seed") and args.perturbation_seed is not None:
            config.perturbation_seed = args.perturbation_seed
        if hasattr(args, "perturbation_phase_scope") and args.perturbation_phase_scope:
            config.perturbation_phase_scope = args.perturbation_phase_scope

        # Override from environment
        config.chatoverflow_api_url = os.environ.get(
            "CHATOVERFLOW_API_URL", config.chatoverflow_api_url
        )
        config.langfuse_secret_key = os.environ.get(
            "LANGFUSE_SECRET_KEY", config.langfuse_secret_key
        )
        config.langfuse_public_key = os.environ.get(
            "LANGFUSE_PUBLIC_KEY", config.langfuse_public_key
        )
        config.langfuse_base_url = os.environ.get(
            "LANGFUSE_BASE_URL", config.langfuse_base_url
        )
        config.perturbation_mode = os.environ.get(
            "PERTURBATION_MODE", config.perturbation_mode
        )

        env_intensity = os.environ.get("PERTURBATION_INTENSITY")
        if env_intensity is not None:
            try:
                config.perturbation_intensity = float(env_intensity)
            except ValueError:
                pass

        env_targets = os.environ.get("PERTURBATION_TARGET_TOOLS")
        if env_targets:
            parsed_targets = [
                tool.strip() for tool in env_targets.split(",") if tool.strip()
            ]
            if parsed_targets:
                config.perturbation_target_tools = parsed_targets

        env_seed = os.environ.get("PERTURBATION_SEED")
        if env_seed is not None:
            try:
                config.perturbation_seed = int(env_seed)
            except ValueError:
                pass

        config.perturbation_phase_scope = os.environ.get(
            "PERTURBATION_PHASE_SCOPE", config.perturbation_phase_scope
        )

        # Backward compatibility: historical runs used intensity with no mode.
        if (
            config.perturbation_mode == "off"
            and config.perturbation_intensity > 0
        ):
            config.perturbation_mode = "context_uncertainty"

        return config

    def ensure_dirs(self):
        """Create required directories."""
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)
