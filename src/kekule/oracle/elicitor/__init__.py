"""
Multi-agent rule elicitation pipeline.

Three-phase pipeline:
  1. Conversation Agent -- multi-turn intent capture with the user
  2. Rule Generator -- converts intent into structured, testable Rules
  3. Reviewer -- audits rules for measurability gaps, auto-resolves or escalates
"""

import json
import logging
from pathlib import Path

from ..schemas import Rule

logger = logging.getLogger(__name__)


def load_rules_from_file(path: str | Path) -> list[Rule]:
    """Load rules from a JSON file.

    Supports two formats:
        {"rules": [{"id": "...", "description": "...", ...}, ...]}
    or:
        [{"id": "...", "description": "...", ...}, ...]

    Args:
        path: Path to the JSON file.

    Returns:
        List of validated Rule objects.

    Raises:
        FileNotFoundError: If the file does not exist.
        pydantic.ValidationError: If a rule fails validation.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Rules file not found: {path}")

    with open(path) as f:
        data = json.load(f)

    if isinstance(data, list):
        raw_rules = data
    elif isinstance(data, dict) and "rules" in data:
        raw_rules = data["rules"]
    else:
        raise ValueError(
            f"Invalid rules file format. Expected a JSON array or "
            f"an object with a 'rules' key, got: {type(data).__name__}"
        )

    return [Rule(**r) for r in raw_rules]


def _parse_rules_from_text(text: str) -> list[Rule]:
    """Parse Rule objects from agent text output.

    Tries to extract a JSON object or array from the text,
    handling cases where the JSON is embedded in markdown.
    """
    text = text.strip()

    # Try to find JSON in markdown code fences
    if "```" in text:
        parts = text.split("```")
        for i, part in enumerate(parts):
            if i % 2 == 1:  # Inside code fence
                content = part.strip()
                if content.startswith(("json", "JSON")):
                    content = content.split("\n", 1)[1] if "\n" in content else ""
                content = content.strip()
                if content:
                    try:
                        return _parse_json_rules(content)
                    except (json.JSONDecodeError, ValueError):
                        continue

    # Try parsing the entire text as JSON
    try:
        return _parse_json_rules(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Try finding JSON object/array boundaries
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start != -1 and end > start:
            try:
                return _parse_json_rules(text[start : end + 1])
            except (json.JSONDecodeError, ValueError):
                continue

    logger.warning("Could not parse rules from agent output")
    return []


def _parse_json_rules(text: str) -> list[Rule]:
    """Parse JSON text into Rule objects."""
    data = json.loads(text)

    if isinstance(data, list):
        raw_rules = data
    elif isinstance(data, dict) and "rules" in data:
        raw_rules = data["rules"]
    else:
        raise ValueError("Expected array or object with 'rules' key")

    return [Rule(**r) for r in raw_rules]


def _parse_json_from_text(text: str, model_class=None):
    """Extract and parse JSON from agent text output.

    Like _parse_rules_from_text but returns raw parsed JSON dict/list
    instead of Rule objects. Used by conversation and reviewer phases.
    """
    text = text.strip()

    # Try markdown code fences first
    if "```" in text:
        parts = text.split("```")
        for i, part in enumerate(parts):
            if i % 2 == 1:
                content = part.strip()
                if content.startswith(("json", "JSON")):
                    content = content.split("\n", 1)[1] if "\n" in content else ""
                content = content.strip()
                if content:
                    try:
                        data = json.loads(content)
                        if model_class:
                            return model_class(**data)
                        return data
                    except (json.JSONDecodeError, ValueError):
                        continue

    # Try the whole text
    try:
        data = json.loads(text)
        if model_class:
            return model_class(**data)
        return data
    except (json.JSONDecodeError, ValueError):
        pass

    # Try finding JSON boundaries
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start != -1 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                if model_class:
                    return model_class(**data)
                return data
            except (json.JSONDecodeError, ValueError):
                continue

    return None
