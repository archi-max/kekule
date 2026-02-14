"""
Perturbation policies for benchmark hooks.

Implements deterministic, non-falsifying tool I/O degradations used to stress
coordination and verification behavior in swarm runs.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

_TEST_COMMAND_RE = re.compile(
    r"\b("
    r"pytest|tox|nosetests|unittest|manage\.py\s+test|python\s+-m\s+pytest|"
    r"go\s+test|cargo\s+test|npm\s+test|pnpm\s+test|yarn\s+test|"
    r"mvn\s+test|gradle\s+test|ctest|bazel\s+test"
    r")\b",
    re.IGNORECASE,
)

_EXCEPTION_LINE_RE = re.compile(
    r"^(?:[A-Za-z_][A-Za-z0-9_.]*)(?:Error|Exception|Failure|Interrupt|Exit):"
)


@dataclass(frozen=True)
class PerturbationPolicy:
    """Configuration for hook-level perturbations."""

    mode: str = "off"
    intensity: float = 0.0
    target_tools: tuple[str, ...] = ("Bash",)
    seed: int = 0
    phase_scope: str = "swarm_phase1"

    @property
    def enabled(self) -> bool:
        return self.mode != "off" and self.intensity > 0

    @property
    def policy_id(self) -> str:
        tools = ",".join(self.target_tools) if self.target_tools else "none"
        return (
            f"{self.mode}|intensity={self.intensity:.4f}|"
            f"tools={tools}|seed={self.seed}|phase={self.phase_scope}"
        )

    def phase_allowed(self, phase_tag: str) -> bool:
        return self.phase_scope == "any" or self.phase_scope == phase_tag

    def targets_tool(self, tool_name: str) -> bool:
        if not self.target_tools:
            return False
        return tool_name in self.target_tools


@dataclass
class PostToolPerturbationResult:
    """Decision/result for a PostToolUse perturbation check."""

    eligible: bool
    fired: bool
    reason: str
    transform_type: str
    updated_tool_output: Any | None
    event: dict[str, Any]


def evaluate_post_tool_use_perturbation(
    *,
    policy: PerturbationPolicy,
    phase_tag: str,
    tool_name: str,
    tool_input: Any,
    tool_response: Any,
    tool_use_id: str | None,
) -> PostToolPerturbationResult:
    """
    Evaluate and optionally apply a PostToolUse perturbation.

    The transform is deterministic and non-falsifying: it only redacts/truncates
    parts of tool output and never modifies command inputs, exit codes, or files.
    """
    output_hash_before = _hash_any(tool_response)
    event = {
        "policy_id": policy.policy_id,
        "mode": policy.mode,
        "phase": phase_tag,
        "tool_name": tool_name,
        "tool_use_id": tool_use_id or "",
        "intensity": policy.intensity,
        "input_hash": _hash_any(tool_input),
        "output_hash_before": output_hash_before,
        "output_hash_after": output_hash_before,
        "eligible": False,
        "fired": False,
        "reason": "",
        "transform_type": "none",
    }

    # Eligibility and gating
    if not policy.enabled:
        return _result(event, "policy_disabled")
    if not policy.phase_allowed(phase_tag):
        return _result(event, "phase_not_allowed")
    if policy.mode != "tool_io_degrade":
        return _result(event, "mode_not_supported_for_post_tool_use")
    if not policy.targets_tool(tool_name):
        return _result(event, "tool_not_targeted")

    if tool_name == "Bash":
        command = _extract_bash_command(tool_input)
        if not _looks_like_verification_command(command):
            return _result(event, "bash_command_not_verification")

    event["eligible"] = True
    roll = _deterministic_roll(
        seed=policy.seed,
        mode=policy.mode,
        intensity=policy.intensity,
        phase_tag=phase_tag,
        tool_name=tool_name,
        tool_use_id=tool_use_id or "",
        tool_input=tool_input,
    )
    event["roll"] = roll
    if roll >= policy.intensity:
        return _result(event, "sampled_out")

    transformed, changed, transform_type = _degrade_tool_response(tool_response)
    if not changed:
        return _result(event, "no_transformable_output")

    event["fired"] = True
    event["transform_type"] = transform_type
    event["output_hash_after"] = _hash_any(transformed)
    event["reason"] = "perturbation_applied"

    return PostToolPerturbationResult(
        eligible=True,
        fired=True,
        reason="perturbation_applied",
        transform_type=transform_type,
        updated_tool_output=transformed,
        event=event,
    )


def _result(event: dict[str, Any], reason: str) -> PostToolPerturbationResult:
    event["reason"] = reason
    return PostToolPerturbationResult(
        eligible=bool(event["eligible"]),
        fired=bool(event["fired"]),
        reason=reason,
        transform_type=str(event["transform_type"]),
        updated_tool_output=None,
        event=event,
    )


def _extract_bash_command(tool_input: Any) -> str:
    if isinstance(tool_input, dict):
        command = tool_input.get("command")
        if isinstance(command, str):
            return command
    if isinstance(tool_input, str):
        return tool_input
    return ""


def _looks_like_verification_command(command: str) -> bool:
    if not command.strip():
        return False
    return bool(_TEST_COMMAND_RE.search(command))


def _degrade_tool_response(tool_response: Any) -> tuple[Any, bool, str]:
    tags: list[str] = []
    transformed, changed = _transform_value(tool_response, tags)
    if not changed:
        return tool_response, False, "none"
    transform_type = "+".join(sorted(set(tags))) if tags else "redaction"
    return transformed, True, transform_type


def _transform_value(value: Any, tags: list[str]) -> tuple[Any, bool]:
    if isinstance(value, str):
        return _degrade_text(value, tags)

    if isinstance(value, list):
        changed = False
        transformed_list = []
        for item in value:
            transformed_item, item_changed = _transform_value(item, tags)
            changed = changed or item_changed
            transformed_list.append(transformed_item)
        return transformed_list, changed

    if isinstance(value, dict):
        changed = False
        transformed_dict: dict[Any, Any] = {}
        for k, v in value.items():
            transformed_v, v_changed = _transform_value(v, tags)
            changed = changed or v_changed
            transformed_dict[k] = transformed_v
        return transformed_dict, changed

    return value, False


def _degrade_text(text: str, tags: list[str]) -> tuple[str, bool]:
    changed = False
    current = text

    redacted = _redact_tracebacks(current)
    if redacted != current:
        current = redacted
        changed = True
        tags.append("traceback_redaction")

    line_capped = _cap_lines(current, head_lines=80, tail_lines=30, max_lines=130)
    if line_capped != current:
        current = line_capped
        changed = True
        tags.append("line_cap")

    truncated = _truncate_head_tail(current, head_chars=1200, tail_chars=800, max_chars=2400)
    if truncated != current:
        current = truncated
        changed = True
        tags.append("head_tail_truncation")

    return current, changed


def _redact_tracebacks(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return text

    output: list[str] = []
    i = 0
    changed = False
    while i < len(lines):
        line = lines[i]
        if line.startswith("Traceback (most recent call last):"):
            changed = True
            output.append(line)
            output.append("[... traceback frames redacted by perturbation policy ...]")

            j = i + 1
            last_exception_line = ""
            while j < len(lines):
                candidate = lines[j].strip()
                if _EXCEPTION_LINE_RE.match(candidate):
                    last_exception_line = lines[j]
                    j += 1
                    break
                if candidate == "":
                    j += 1
                    break
                j += 1

            if last_exception_line:
                output.append(last_exception_line)
            i = j
            continue

        output.append(line)
        i += 1

    if not changed:
        return text
    return "\n".join(output)


def _cap_lines(text: str, head_lines: int, tail_lines: int, max_lines: int) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text

    removed = len(lines) - (head_lines + tail_lines)
    body = lines[:head_lines]
    body.append(
        f"[... {removed} lines omitted by perturbation policy for verification output ...]"
    )
    body.extend(lines[-tail_lines:])
    return "\n".join(body)


def _truncate_head_tail(text: str, head_chars: int, tail_chars: int, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text

    removed = len(text) - (head_chars + tail_chars)
    return (
        f"{text[:head_chars]}\n"
        f"[... {removed} characters truncated by perturbation policy ...]\n"
        f"{text[-tail_chars:]}"
    )


def _deterministic_roll(
    *,
    seed: int,
    mode: str,
    intensity: float,
    phase_tag: str,
    tool_name: str,
    tool_use_id: str,
    tool_input: Any,
) -> float:
    material = (
        f"{seed}|{mode}|{intensity:.6f}|{phase_tag}|{tool_name}|{tool_use_id}|"
        f"{_hash_any(tool_input)}"
    ).encode("utf-8")
    digest = hashlib.sha256(material).digest()
    value = int.from_bytes(digest[:8], byteorder="big", signed=False)
    return value / float(2**64)


def _hash_any(value: Any) -> str:
    try:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    except Exception:
        payload = repr(value)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
