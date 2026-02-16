"""Tests for oracle schemas."""

import pytest
from pydantic import ValidationError

from kekule.oracle.schemas import (
    OracleResult,
    OracleRunRequest,
    OracleType,
    Rule,
    RuleStatus,
)


class TestRule:
    def test_create_minimal_rule(self):
        rule = Rule(id="test_login", description="Login should return 200")
        assert rule.id == "test_login"
        assert rule.oracle_type == OracleType.PYTEST
        assert rule.status == RuleStatus.DRAFT
        assert rule.uncertainty == 0.5
        assert rule.oracle_config == {}

    def test_create_full_rule(self):
        rule = Rule(
            id="test_auth",
            description="Auth endpoint returns JWT",
            oracle_type=OracleType.PYTEST,
            oracle_config={"target_module": "auth.views", "expected_status": 200},
            uncertainty=0.1,
            status=RuleStatus.CONFIRMED,
        )
        assert rule.oracle_config["target_module"] == "auth.views"
        assert rule.uncertainty == 0.1
        assert rule.status == RuleStatus.CONFIRMED

    def test_uncertainty_too_high(self):
        with pytest.raises(ValidationError):
            Rule(id="x", description="y", uncertainty=1.5)

    def test_uncertainty_too_low(self):
        with pytest.raises(ValidationError):
            Rule(id="x", description="y", uncertainty=-0.1)

    def test_uncertainty_boundary_values(self):
        rule_zero = Rule(id="x", description="y", uncertainty=0.0)
        assert rule_zero.uncertainty == 0.0

        rule_one = Rule(id="x", description="y", uncertainty=1.0)
        assert rule_one.uncertainty == 1.0

    def test_json_roundtrip(self):
        rule = Rule(
            id="test",
            description="desc",
            oracle_config={"key": "value"},
            uncertainty=0.3,
        )
        data = rule.model_dump()
        reconstructed = Rule(**data)
        assert reconstructed == rule

    def test_json_serialization(self):
        rule = Rule(id="test", description="desc")
        json_str = rule.model_dump_json()
        assert "test" in json_str
        assert "desc" in json_str
        assert "pytest" in json_str

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            Rule(id="x")  # missing description

        with pytest.raises(ValidationError):
            Rule(description="y")  # missing id

    def test_enum_values(self):
        assert OracleType.PYTEST.value == "pytest"
        assert RuleStatus.DRAFT.value == "draft"
        assert RuleStatus.CONFIRMED.value == "confirmed"
        assert RuleStatus.VERIFIED.value == "verified"


class TestOracleResult:
    def test_passed_result(self):
        result = OracleResult(
            rule_id="r1", passed=True, exit_code=0, execution_time_s=1.5
        )
        assert result.passed is True
        assert result.exit_code == 0

    def test_failed_result(self):
        result = OracleResult(
            rule_id="r1",
            passed=False,
            exit_code=1,
            evidence="FAILED test_x - AssertionError",
        )
        assert result.passed is False
        assert "FAILED" in result.evidence

    def test_defaults(self):
        result = OracleResult(rule_id="r1", passed=True)
        assert result.evidence == ""
        assert result.artifact_path == ""
        assert result.execution_time_s == 0.0
        assert result.exit_code == -1


class TestOracleRunRequest:
    def test_local_repo(self):
        req = OracleRunRequest(
            repo_path="/tmp/my-repo",
            rules=[Rule(id="r1", description="test")],
        )
        assert req.repo_url is None
        assert req.repo_path == "/tmp/my-repo"
        assert req.docker_image == "python:3.11-slim"
        assert req.timeout_s == 300

    def test_remote_repo(self):
        req = OracleRunRequest(
            repo_url="https://github.com/user/repo.git",
            git_commit="abc123def456",
            rules=[Rule(id="r1", description="test")],
        )
        assert req.repo_url is not None
        assert req.git_commit == "abc123def456"

    def test_custom_docker_image(self):
        req = OracleRunRequest(
            repo_path="/tmp/repo",
            rules=[Rule(id="r1", description="test")],
            docker_image="python:3.12-bookworm",
            timeout_s=600,
        )
        assert req.docker_image == "python:3.12-bookworm"
        assert req.timeout_s == 600

    def test_multiple_rules(self):
        rules = [
            Rule(id="r1", description="test 1"),
            Rule(id="r2", description="test 2"),
            Rule(id="r3", description="test 3"),
        ]
        req = OracleRunRequest(repo_path="/tmp/repo", rules=rules)
        assert len(req.rules) == 3
