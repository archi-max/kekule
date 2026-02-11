"""
SWE-bench Lite task selection.

Loads the dataset from HuggingFace and picks medium/hard problems
that benefit from collaborative solving (multi-file, complex reasoning).
"""

import logging
import os
from dataclasses import dataclass

# Disable XET for HuggingFace to avoid issues
os.environ["HF_HUB_DISABLE_XET"] = "1"

from datasets import load_dataset

logger = logging.getLogger(__name__)

# Hand-picked medium/hard SWE-bench Lite instances.
# These require deep codebase understanding and multi-file reasoning.
DEFAULT_TASK_IDS = [
    # Django: file-based cache race condition fix (TOCTOU bug in has_key)
    "django__django-16379",
    # Django: ModelChoiceIteratorValue is not hashable (after 3.0->3.1 migration)
    "django__django-14915",
    # Pytest: str() on pytest.raises context behaves differently from normal exception
    "pytest-dev__pytest-5413",
]


@dataclass
class SWETask:
    """A single SWE-bench task with all fields needed for solving + evaluation."""

    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    patch: str  # Gold patch for reference (not shown to agents)
    test_patch: str
    hints_text: str
    version: str

    @property
    def repo_url(self) -> str:
        return f"https://github.com/{self.repo}.git"

    @property
    def short_id(self) -> str:
        return self.instance_id.split("__")[-1]


def load_swebench_lite() -> list[dict]:
    """Load the full SWE-bench Lite dataset."""
    logger.info("Loading SWE-bench Lite dataset from HuggingFace...")
    ds = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
    logger.info(f"Loaded {len(ds)} instances")
    return list(ds)


SMALL_REPOS = [
    "pytest-dev/pytest",
    "psf/requests",
    "pallets/flask",
    "pylint-dev/pylint",
    "pydata/xarray",
    "mwaskom/seaborn",
    "sphinx-doc/sphinx",
]


def select_tasks(
    task_ids: list[str] | None = None,
    num_problems: int = 3,
    repos: list[str] | None = None,
) -> list[SWETask]:
    """
    Select SWE-bench tasks for the experiment.

    Args:
        task_ids: Explicit list of instance IDs. If None, uses DEFAULT_TASK_IDS.
        num_problems: Number of problems to select (only used for auto-selection).
        repos: If provided, select all tasks from these repos (up to num_problems).

    Returns:
        List of SWETask objects.
    """
    all_instances = load_swebench_lite()
    id_to_instance = {inst["instance_id"]: inst for inst in all_instances}

    if repos:
        # Select all tasks from specified repos
        ids_to_use = [
            inst["instance_id"]
            for inst in all_instances
            if inst["repo"] in repos
        ][:num_problems]
    elif task_ids:
        ids_to_use = task_ids
    else:
        ids_to_use = DEFAULT_TASK_IDS[:num_problems]

    tasks = []
    for task_id in ids_to_use:
        if task_id not in id_to_instance:
            logger.warning(f"Task {task_id} not found in SWE-bench Lite, skipping")
            continue

        inst = id_to_instance[task_id]
        tasks.append(
            SWETask(
                instance_id=inst["instance_id"],
                repo=inst["repo"],
                base_commit=inst["base_commit"],
                problem_statement=inst["problem_statement"],
                patch=inst["patch"],
                test_patch=inst["test_patch"],
                hints_text=inst.get("hints_text", ""),
                version=inst.get("version", ""),
            )
        )

    if not tasks:
        raise ValueError(
            f"No valid tasks found. Requested IDs: {ids_to_use}. "
            f"Available: {list(id_to_instance.keys())[:10]}..."
        )

    logger.info(f"Selected {len(tasks)} tasks: {[t.instance_id for t in tasks]}")
    return tasks


def list_available_tasks() -> list[str]:
    """List all available SWE-bench Lite instance IDs."""
    instances = load_swebench_lite()
    return [inst["instance_id"] for inst in instances]
