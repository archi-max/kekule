"""
Deterministic train/test splitting of SWE-bench tasks.

Splits tasks into train (used for analysis + prompt improvement) and test
(used only for evaluation, no log access) sets. The split is deterministic
by hash of instance_id so it's reproducible across runs without storing state.
"""

import hashlib
import json
import logging
from pathlib import Path

from .task_selector import SWETask

logger = logging.getLogger(__name__)


def _hash_bucket(instance_id: str, seed: int = 42) -> float:
    """Map an instance_id to a deterministic float in [0, 1).

    Uses SHA-256 hash of (seed, instance_id) for uniform distribution.
    """
    h = hashlib.sha256(f"{seed}:{instance_id}".encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def split_tasks(
    tasks: list[SWETask],
    train_ratio: float = 0.7,
    seed: int = 42,
) -> tuple[list[SWETask], list[SWETask]]:
    """Split tasks into train and test sets.

    Args:
        tasks: Full list of SWE-bench tasks.
        train_ratio: Fraction of tasks for training (0.0 to 1.0).
        seed: Hash seed for deterministic splitting.

    Returns:
        (train_tasks, test_tasks) tuple.
    """
    if not 0.0 < train_ratio < 1.0:
        raise ValueError(f"train_ratio must be in (0, 1), got {train_ratio}")

    train: list[SWETask] = []
    test: list[SWETask] = []

    for task in tasks:
        if _hash_bucket(task.instance_id, seed) < train_ratio:
            train.append(task)
        else:
            test.append(task)

    # Guarantee at least 1 task in each split if we have >= 2 tasks
    if len(tasks) >= 2:
        if not train:
            train.append(test.pop(0))
        elif not test:
            test.append(train.pop(-1))

    logger.info(
        f"Split {len(tasks)} tasks: {len(train)} train, {len(test)} test "
        f"(ratio={train_ratio}, seed={seed})"
    )
    return train, test


def split_tasks_from_files(
    tasks: list[SWETask],
    train_ids_file: str | Path | None = None,
    test_ids_file: str | Path | None = None,
) -> tuple[list[SWETask], list[SWETask]]:
    """Split tasks using explicit ID files.

    Each file should be a JSON with a "task_ids" array.
    Tasks not in either file are dropped.

    Args:
        tasks: Full list of SWE-bench tasks.
        train_ids_file: JSON file with train task IDs.
        test_ids_file: JSON file with test task IDs.

    Returns:
        (train_tasks, test_tasks) tuple.
    """
    task_map = {t.instance_id: t for t in tasks}

    train_ids: set[str] = set()
    test_ids: set[str] = set()

    if train_ids_file:
        with open(train_ids_file) as f:
            data = json.load(f)
        train_ids = set(data.get("task_ids", []))

    if test_ids_file:
        with open(test_ids_file) as f:
            data = json.load(f)
        test_ids = set(data.get("task_ids", []))

    # Validate no overlap
    overlap = train_ids & test_ids
    if overlap:
        raise ValueError(
            f"Train/test ID files overlap on {len(overlap)} tasks: "
            f"{list(overlap)[:5]}..."
        )

    train = [task_map[tid] for tid in train_ids if tid in task_map]
    test = [task_map[tid] for tid in test_ids if tid in task_map]

    missing_train = train_ids - set(task_map.keys())
    missing_test = test_ids - set(task_map.keys())
    if missing_train:
        logger.warning(f"Train IDs not found in dataset: {missing_train}")
    if missing_test:
        logger.warning(f"Test IDs not found in dataset: {missing_test}")

    logger.info(f"Split from files: {len(train)} train, {len(test)} test")
    return train, test
