"""Tests for oracle rule elicitor."""

import json

import pytest

from kekule.oracle.elicitor import (
    _parse_rules_from_text,
    load_rules_from_file,
)
from kekule.oracle.schemas import OracleType, Rule


class TestLoadRulesFromFile:
    def test_load_array_format(self, tmp_path):
        rules_file = tmp_path / "rules.json"
        rules_file.write_text(
            json.dumps([
                {"id": "r1", "description": "Test login"},
                {"id": "r2", "description": "Test logout"},
            ])
        )
        rules = load_rules_from_file(rules_file)
        assert len(rules) == 2
        assert rules[0].id == "r1"
        assert rules[1].id == "r2"

    def test_load_object_format(self, tmp_path):
        rules_file = tmp_path / "rules.json"
        rules_file.write_text(
            json.dumps({
                "rules": [
                    {"id": "r1", "description": "Test login"},
                ]
            })
        )
        rules = load_rules_from_file(rules_file)
        assert len(rules) == 1
        assert rules[0].id == "r1"

    def test_load_with_full_fields(self, tmp_path):
        rules_file = tmp_path / "rules.json"
        rules_file.write_text(
            json.dumps([{
                "id": "auth_check",
                "description": "Auth returns token",
                "oracle_type": "pytest",
                "oracle_config": {"module": "auth"},
                "uncertainty": 0.2,
                "status": "confirmed",
            }])
        )
        rules = load_rules_from_file(rules_file)
        assert len(rules) == 1
        assert rules[0].oracle_type == OracleType.PYTEST
        assert rules[0].oracle_config == {"module": "auth"}
        assert rules[0].uncertainty == 0.2

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_rules_from_file("/nonexistent/rules.json")

    def test_validation_error(self, tmp_path):
        rules_file = tmp_path / "rules.json"
        rules_file.write_text(json.dumps([{"not_a_rule": True}]))
        with pytest.raises(Exception):
            load_rules_from_file(rules_file)

    def test_invalid_format(self, tmp_path):
        rules_file = tmp_path / "rules.json"
        rules_file.write_text(json.dumps({"not_rules": []}))
        with pytest.raises(ValueError, match="Invalid rules file format"):
            load_rules_from_file(rules_file)

    def test_empty_array(self, tmp_path):
        rules_file = tmp_path / "rules.json"
        rules_file.write_text(json.dumps([]))
        rules = load_rules_from_file(rules_file)
        assert len(rules) == 0

    def test_load_from_string_path(self, tmp_path):
        rules_file = tmp_path / "rules.json"
        rules_file.write_text(
            json.dumps([{"id": "r1", "description": "Test"}])
        )
        rules = load_rules_from_file(str(rules_file))
        assert len(rules) == 1


class TestParseRulesFromText:
    def test_parse_plain_json_object(self):
        text = json.dumps({
            "rules": [
                {"id": "r1", "description": "Test login"},
            ]
        })
        rules = _parse_rules_from_text(text)
        assert len(rules) == 1
        assert rules[0].id == "r1"

    def test_parse_plain_json_array(self):
        text = json.dumps([
            {"id": "r1", "description": "Test login"},
            {"id": "r2", "description": "Test logout"},
        ])
        rules = _parse_rules_from_text(text)
        assert len(rules) == 2

    def test_parse_json_in_code_fence(self):
        text = """Here are the rules I proposed:

```json
{
  "rules": [
    {"id": "r1", "description": "Test login"}
  ]
}
```

Let me know if you want to adjust any of these."""
        rules = _parse_rules_from_text(text)
        assert len(rules) == 1
        assert rules[0].id == "r1"

    def test_parse_json_in_plain_code_fence(self):
        text = """```
[{"id": "r1", "description": "Test"}]
```"""
        rules = _parse_rules_from_text(text)
        assert len(rules) == 1

    def test_parse_json_embedded_in_text(self):
        text = 'Some text before {"rules": [{"id": "r1", "description": "Test"}]} some text after'
        rules = _parse_rules_from_text(text)
        assert len(rules) == 1

    def test_parse_unparseable_text(self):
        text = "This is not JSON at all, just plain text."
        rules = _parse_rules_from_text(text)
        assert len(rules) == 0

    def test_parse_empty_rules(self):
        text = json.dumps({"rules": []})
        rules = _parse_rules_from_text(text)
        assert len(rules) == 0
