"""
Patch hygiene utilities.

Sanitizes git diff payloads before they are written to SWE-bench predictions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

_DIFF_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_NOISY_DOCICONS_RE = re.compile(r"^docs/_theme/djangodocs-epub/static/docicons-")
_SYMLINK_MODE_RE = re.compile(
    r"^(?:new file mode|old mode|deleted file mode) 120000$",
    re.MULTILINE,
)
_BINARY_MARKER_RE = re.compile(
    r"^(?:GIT binary patch|Binary files .+ differ)$",
    re.MULTILINE,
)
_HUNK_RE = re.compile(r"^@@ ", re.MULTILINE)

_DEFAULT_DROP_PREFIXES = (
    "swarm_ledger/",
    ".pytest_cache/",
    "__pycache__/",
)


@dataclass(frozen=True)
class PatchSanitizationResult:
    patch: str
    kept_files: tuple[str, ...]
    dropped_files: tuple[str, ...]
    rejected: bool
    reason: str = ""


def extract_changed_files(patch_text: str) -> set[str]:
    """Extract changed file paths from a unified git patch."""
    files: set[str] = set()
    for section in _split_diff_sections(patch_text):
        path = _parse_section_path(section)
        if path:
            files.add(path)
    return files


def sanitize_patch(
    patch_text: str,
    *,
    allowed_files: Iterable[str] | None = None,
    fail_closed_on_special: bool = True,
) -> PatchSanitizationResult:
    """
    Sanitize a patch by removing noisy sections and optionally rejecting unsafe ones.

    Unsafe sections are binary/symlink diffs. Noisy sections are known unrelated
    generated artifacts (for example, Django docicons).
    """
    sections = _split_diff_sections(patch_text)
    if not sections:
        return PatchSanitizationResult(
            patch="",
            kept_files=(),
            dropped_files=(),
            rejected=False,
        )

    allowed = set(allowed_files) if allowed_files is not None else None
    kept_sections: list[str] = []
    kept_files: list[str] = []
    dropped_files: list[str] = []

    for section in sections:
        path = _parse_section_path(section)
        if not path:
            continue

        if _is_noisy_path(path):
            dropped_files.append(path)
            continue
        if allowed is not None and path not in allowed:
            dropped_files.append(path)
            continue
        if _contains_special_hunks(section):
            if fail_closed_on_special:
                return PatchSanitizationResult(
                    patch="",
                    kept_files=tuple(sorted(set(kept_files))),
                    dropped_files=tuple(sorted(set(dropped_files + [path]))),
                    rejected=True,
                    reason=f"special_hunk:{path}",
                )
            dropped_files.append(path)
            continue
        if not _HUNK_RE.search(section):
            dropped_files.append(path)
            continue

        kept_sections.append(_ensure_trailing_newline(section))
        kept_files.append(path)

    sanitized = "".join(kept_sections)
    return PatchSanitizationResult(
        patch=sanitized,
        kept_files=tuple(sorted(set(kept_files))),
        dropped_files=tuple(sorted(set(dropped_files))),
        rejected=False,
    )


def _contains_special_hunks(section: str) -> bool:
    return bool(_SYMLINK_MODE_RE.search(section) or _BINARY_MARKER_RE.search(section))


def _is_noisy_path(path: str) -> bool:
    if _NOISY_DOCICONS_RE.match(path):
        return True
    return any(path.startswith(prefix) for prefix in _DEFAULT_DROP_PREFIXES)


def _parse_section_path(section: str) -> str | None:
    first_line = section.splitlines()[0] if section else ""
    match = _DIFF_HEADER_RE.match(first_line)
    if not match:
        return None
    path = match.group(2)
    return path.strip('"')


def _split_diff_sections(patch_text: str) -> list[str]:
    sections: list[list[str]] = []
    current: list[str] = []
    for line in patch_text.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current:
                sections.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        sections.append(current)
    return ["".join(section) for section in sections]


def _ensure_trailing_newline(text: str) -> str:
    return text if text.endswith("\n") else f"{text}\n"
