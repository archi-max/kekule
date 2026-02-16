"""
Prompt Configuration -- makes all system prompts configurable and versionable.

Prompts can be:
  1. Loaded from a prompts directory (text files)
  2. Overridden at runtime via PromptConfig
  3. Snapshot per epoch for reproducibility
  4. Modified by the waypoint coordinator across epochs

Each prompt has a key (e.g., "swarm_protocol", "planner", "coordinator") and
a default value hardcoded in the source. File overrides take precedence.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default prompts (imported from their source modules on first access)
# ---------------------------------------------------------------------------

_DEFAULTS_LOADED = False
_DEFAULTS: dict[str, str] = {}


def _load_defaults() -> dict[str, str]:
    """Lazily load default prompts from source modules."""
    global _DEFAULTS_LOADED, _DEFAULTS
    if _DEFAULTS_LOADED:
        return _DEFAULTS

    from .solver_agent import SWE_SOLVER_SYSTEM_PROMPT
    from .solvers.perturbation_swarm import (
        PLANNER_PROMPT,
        SWARM_PROTOCOL_PROMPT,
    )
    from .oracle_bridge import (
        UNIT_TEST_PROMPT,
        REGRESSION_CHECK_PROMPT,
        BEHAVIORAL_ASSERTION_PROMPT,
    )
    from .waypoint_coordinator import COORDINATOR_SYSTEM_PROMPT
    from .solvers.oracle_swarm import ORACLE_ROLE_PROMPT

    _DEFAULTS = {
        "swe_solver": SWE_SOLVER_SYSTEM_PROMPT,
        "swarm_protocol": SWARM_PROTOCOL_PROMPT,
        "planner": PLANNER_PROMPT,
        "oracle_unit_test": UNIT_TEST_PROMPT,
        "oracle_regression_check": REGRESSION_CHECK_PROMPT,
        "oracle_behavioral_assertion": BEHAVIORAL_ASSERTION_PROMPT,
        "coordinator": COORDINATOR_SYSTEM_PROMPT,
        "oracle_role": ORACLE_ROLE_PROMPT,
    }
    _DEFAULTS_LOADED = True
    return _DEFAULTS


# ---------------------------------------------------------------------------
# Prompt registry
# ---------------------------------------------------------------------------

# All known prompt keys and their descriptions
PROMPT_KEYS = {
    "swe_solver": "System prompt for the default SWE-bench solver agent",
    "swarm_protocol": "System prompt template for swarm agents (has {placeholders})",
    "planner": "Prompt for the role planner agent that decomposes tasks into roles",
    "oracle_unit_test": "System prompt for the unit test oracle generator",
    "oracle_regression_check": "System prompt for the regression check oracle generator",
    "oracle_behavioral_assertion": "System prompt for the behavioral assertion oracle generator",
    "coordinator": "System prompt for the waypoint coordinator agent",
    "oracle_role": "System prompt template for oracle agents as swarm roles",
}


@dataclass
class PromptConfig:
    """Manages all configurable prompts for the self-improving harness.

    Prompts are resolved in order:
      1. Runtime overrides (set via code or coordinator adjustments)
      2. File overrides (loaded from prompts_dir)
      3. Hardcoded defaults (from source modules)
    """

    prompts_dir: Path | None = None
    overrides: dict[str, str] = field(default_factory=dict)

    def get(self, key: str) -> str:
        """Get a prompt by key, with override resolution."""
        # 1. Runtime override
        if key in self.overrides:
            return self.overrides[key]

        # 2. File override
        if self.prompts_dir:
            file_path = self.prompts_dir / f"{key}.md"
            if file_path.exists():
                return file_path.read_text()
            # Also check .txt extension
            file_path = self.prompts_dir / f"{key}.txt"
            if file_path.exists():
                return file_path.read_text()

        # 3. Hardcoded default
        defaults = _load_defaults()
        if key in defaults:
            return defaults[key]

        raise KeyError(
            f"Unknown prompt key: '{key}'. "
            f"Available keys: {list(PROMPT_KEYS.keys())}"
        )

    def set(self, key: str, value: str) -> None:
        """Set a runtime override for a prompt."""
        self.overrides[key] = value

    def list_keys(self) -> dict[str, str]:
        """List all available prompt keys and descriptions."""
        return dict(PROMPT_KEYS)

    def get_all(self) -> dict[str, str]:
        """Get all prompts (resolved)."""
        result = {}
        for key in PROMPT_KEYS:
            try:
                result[key] = self.get(key)
            except KeyError:
                pass
        return result

    def snapshot(self) -> dict[str, str]:
        """Create a snapshot of all current prompt values.

        Returns a dict mapping key -> current prompt text.
        Useful for saving per-epoch state.
        """
        return self.get_all()

    def save_snapshot(self, path: Path) -> None:
        """Save a prompt snapshot to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.snapshot()
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved prompt snapshot to {path} ({len(data)} prompts)")

    def save_to_dir(self, dir_path: Path) -> None:
        """Save all prompts as individual files in a directory.

        Each prompt is saved as {key}.md for easy editing.
        """
        dir_path.mkdir(parents=True, exist_ok=True)
        for key, text in self.get_all().items():
            file_path = dir_path / f"{key}.md"
            file_path.write_text(text)
        logger.info(f"Saved {len(PROMPT_KEYS)} prompts to {dir_path}")

    @classmethod
    def from_dir(cls, prompts_dir: str | Path) -> "PromptConfig":
        """Create a PromptConfig that loads overrides from a directory."""
        return cls(prompts_dir=Path(prompts_dir))

    @classmethod
    def from_snapshot(cls, path: str | Path) -> "PromptConfig":
        """Create a PromptConfig from a saved snapshot JSON file."""
        path = Path(path)
        with open(path) as f:
            data = json.load(f)
        return cls(overrides=data)

    def apply_coordinator_prompt_changes(self, changes: dict) -> None:
        """Apply prompt changes from the waypoint coordinator.

        The coordinator can output a 'prompt_changes' dict with
        key -> new_text mappings to modify base prompts.

        Args:
            changes: Dict mapping prompt key -> new prompt text.
                     Only known keys are accepted.
        """
        for key, value in changes.items():
            if key not in PROMPT_KEYS:
                logger.warning(
                    f"Coordinator suggested unknown prompt key: '{key}', skipping"
                )
                continue
            if not isinstance(value, str):
                logger.warning(
                    f"Coordinator prompt change for '{key}' is not a string, skipping"
                )
                continue
            self.overrides[key] = value
            logger.info(
                f"Applied coordinator prompt change: '{key}' "
                f"({len(value)} chars)"
            )
