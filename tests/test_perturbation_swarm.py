"""Tests for perturbation swarm solver parsing and design logic."""


from kekule.benchmarks.solvers.perturbation_swarm import (
    _parse_planner_json,
    _validate_roles,
    _get_swarm_design_text,
    _get_perturbation_text,
    DEFAULT_DEPENDENCIES,
)


class TestParserPlannerJson:
    def test_parse_full_object(self):
        text = """{
          "roles": [
            {"name": "test_runner", "goal": "Run tests"},
            {"name": "fixer", "goal": "Fix the bug"}
          ],
          "dependencies": [["fixer", "test_runner"]],
          "swarm_design": "coordinator"
        }"""
        result = _parse_planner_json(text)
        assert result is not None
        assert len(result["roles"]) == 2
        assert result["dependencies"] == [["fixer", "test_runner"]]
        assert result["swarm_design"] == "coordinator"

    def test_parse_object_with_surrounding_text(self):
        text = """Here is my analysis:
        {
          "roles": [
            {"name": "a", "goal": "Do A"},
            {"name": "b", "goal": "Do B"}
          ],
          "swarm_design": "flat"
        }
        That should work well."""
        result = _parse_planner_json(text)
        assert result is not None
        assert len(result["roles"]) == 2
        assert result["swarm_design"] == "flat"

    def test_parse_object_missing_deps_defaults_empty(self):
        text = """{
          "roles": [
            {"name": "a", "goal": "Do A"},
            {"name": "b", "goal": "Do B"}
          ]
        }"""
        result = _parse_planner_json(text)
        assert result is not None
        assert result["dependencies"] == []
        assert result["swarm_design"] == "flat"

    def test_parse_array_only_backwards_compat(self):
        text = """[
          {"name": "test_runner", "goal": "Run tests"},
          {"name": "fixer", "goal": "Fix bug"}
        ]"""
        result = _parse_planner_json(text)
        assert result is not None
        assert len(result["roles"]) == 2
        assert result["dependencies"] == DEFAULT_DEPENDENCIES
        assert result["swarm_design"] == "flat"

    def test_parse_invalid_json(self):
        result = _parse_planner_json("This is not JSON at all")
        assert result is None

    def test_parse_too_few_roles(self):
        text = """{"roles": [{"name": "a", "goal": "Do A"}]}"""
        result = _parse_planner_json(text)
        assert result is None

    def test_parse_too_many_roles(self):
        text = """{
          "roles": [
            {"name": "a", "goal": "1"},
            {"name": "b", "goal": "2"},
            {"name": "c", "goal": "3"},
            {"name": "d", "goal": "4"},
            {"name": "e", "goal": "5"}
          ]
        }"""
        result = _parse_planner_json(text)
        assert result is None

    def test_parse_missing_fields(self):
        text = """[{"name": "a"}, {"name": "b"}]"""
        result = _parse_planner_json(text)
        assert result is None

    def test_parse_lead_design(self):
        text = """{
          "roles": [
            {"name": "lead", "goal": "Lead"},
            {"name": "worker", "goal": "Work"}
          ],
          "swarm_design": "lead:lead"
        }"""
        result = _parse_planner_json(text)
        assert result is not None
        assert result["swarm_design"] == "lead:lead"


class TestValidateRoles:
    def test_valid_roles(self):
        assert _validate_roles([
            {"name": "a", "goal": "Do A"},
            {"name": "b", "goal": "Do B"},
        ])

    def test_invalid_not_list(self):
        assert not _validate_roles("not a list")

    def test_invalid_too_few(self):
        assert not _validate_roles([{"name": "a", "goal": "Do A"}])

    def test_invalid_too_many(self):
        assert not _validate_roles([
            {"name": str(i), "goal": f"Do {i}"} for i in range(5)
        ])

    def test_invalid_missing_name(self):
        assert not _validate_roles([
            {"goal": "Do A"},
            {"name": "b", "goal": "Do B"},
        ])

    def test_invalid_wrong_type(self):
        assert not _validate_roles([
            {"name": 123, "goal": "Do A"},
            {"name": "b", "goal": "Do B"},
        ])


class TestGetSwarmDesignText:
    def test_flat_design(self):
        text = _get_swarm_design_text("flat", [])
        assert "Flat" in text
        assert "peers" in text.lower()

    def test_coordinator_design(self):
        text = _get_swarm_design_text("coordinator", [])
        assert "Coordinator" in text

    def test_lead_design(self):
        text = _get_swarm_design_text("lead:fixer", [])
        assert "Lead" in text
        assert "fixer" in text

    def test_custom_design(self):
        text = _get_swarm_design_text("All agents pair program", [])
        assert "Custom" in text
        assert "pair program" in text


class TestGetPerturbationText:
    def test_zero_intensity(self):
        assert _get_perturbation_text(0.0) == ""

    def test_negative_intensity(self):
        assert _get_perturbation_text(-0.1) == ""

    def test_low_intensity(self):
        text = _get_perturbation_text(0.05)
        assert "incomplete" in text

    def test_medium_intensity(self):
        text = _get_perturbation_text(0.10)
        assert "alternative explanation" in text

    def test_high_intensity(self):
        text = _get_perturbation_text(0.20)
        assert "disconfirming evidence" in text

    def test_between_levels(self):
        """0.07 should pick the 0.05 level (closest at or below)."""
        text = _get_perturbation_text(0.07)
        assert "incomplete" in text
