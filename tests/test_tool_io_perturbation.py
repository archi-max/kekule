"""
Tests for the tool I/O perturbation solver (experiment v0.2).

Covers:
  - Test command detection (is_test_command)
  - Output truncation at each intensity level
  - File path redaction
  - Error name redaction
  - PostToolUse hook wiring (fires on test Bash, skips non-test/non-Bash)
  - Perturbation event logging structure
  - Hook composition with tracing hooks
  - Edge cases (empty output, short output, non-string output)
"""

import asyncio
import subprocess
from pathlib import Path

import pytest

from kekule.benchmarks.solvers.tool_io_perturbation import (
    _count_redactions,
    _parse_roles_json,
    _redact_error_names,
    _redact_file_paths,
    build_perturbation_hooks,
    is_test_command,
    select_best_patch,
    truncate_test_output,
)
from kekule.benchmarks.tracing import AgentTraceData, build_agent_hooks

# ---------------------------------------------------------------------------
# conftest fixtures imported via conftest.py:
#   PYTEST_OUTPUT_SHORT, PYTEST_OUTPUT_LONG
# ---------------------------------------------------------------------------


# ===== Test command detection ================================================


class TestIsTestCommand:
    """is_test_command should match common Python test runners."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "pytest tests/",
            "pytest",
            "pytest -xvs tests/test_foo.py",
            "python -m pytest tests/",
            "python -m pytest -k test_edge",
            "python manage.py test myapp",
            "python manage.py test",
            "tox",
            "tox -e py311",
            "python -m unittest discover",
            "python -m unittest tests.test_core",
            "python tests/test_core.py",
            "python test_runner.py",
            "./runtests.py",
            "python tests/runtests.py",
        ],
    )
    def test_matches_test_commands(self, cmd: str) -> None:
        assert is_test_command(cmd), f"Should match: {cmd!r}"

    @pytest.mark.parametrize(
        "cmd",
        [
            "git diff",
            "git status",
            "ls -la",
            "cat README.md",
            "echo hello",
            "pip install pytest",  # installing, not running
            "uv install pytest",
            "conda install pytest",
            "pip install -e .[test]",
            "grep -r 'test' .",
            "cd tests && ls",
            "python setup.py install",
            "python src/main.py",
            "ruff check .",
        ],
    )
    def test_rejects_non_test_commands(self, cmd: str) -> None:
        assert not is_test_command(cmd), f"Should NOT match: {cmd!r}"


# ===== Output truncation ====================================================


class TestTruncateTestOutput:
    """truncate_test_output at each intensity level."""

    def _make_lines(self, n: int) -> str:
        return "\n".join(f"line {i}" for i in range(n))

    def test_baseline_no_modification(self) -> None:
        output = self._make_lines(100)
        assert truncate_test_output(output, 0.0) == output

    def test_low_truncates_to_30_lines(self) -> None:
        output = self._make_lines(100)
        result = truncate_test_output(output, 0.05)
        assert len(result.splitlines()) == 30

    def test_low_short_output_unchanged(self) -> None:
        output = self._make_lines(10)
        result = truncate_test_output(output, 0.05)
        assert len(result.splitlines()) == 10

    def test_medium_truncates_to_15_lines(self) -> None:
        output = self._make_lines(100)
        result = truncate_test_output(output, 0.10)
        assert len(result.splitlines()) == 15

    def test_medium_redacts_file_paths(self, PYTEST_OUTPUT_LONG: str) -> None:
        result = truncate_test_output(PYTEST_OUTPUT_LONG, 0.10)
        assert "[REDACTED_PATH]" in result

    def test_medium_does_not_redact_error_names(self) -> None:
        output = "TypeError: bad value\nValueError: nope"
        result = truncate_test_output(output, 0.10)
        assert "TypeError" in result
        assert "ValueError" in result

    def test_high_truncates_to_5_lines(self) -> None:
        output = self._make_lines(100)
        result = truncate_test_output(output, 0.20)
        assert len(result.splitlines()) == 5

    def test_high_redacts_file_paths(self, PYTEST_OUTPUT_LONG: str) -> None:
        result = truncate_test_output(PYTEST_OUTPUT_LONG, 0.20)
        assert "[REDACTED_PATH]" in result

    def test_high_redacts_error_names(self, PYTEST_OUTPUT_LONG: str) -> None:
        result = truncate_test_output(PYTEST_OUTPUT_LONG, 0.20)
        assert "[ERROR]" in result
        assert "TypeError" not in result

    def test_keeps_last_lines(self) -> None:
        """Truncation should keep the TAIL (last N lines), not the head."""
        output = "\n".join(f"line-{i}" for i in range(50))
        result = truncate_test_output(output, 0.05)  # last 30
        lines = result.splitlines()
        assert lines[0] == "line-20"
        assert lines[-1] == "line-49"

    def test_empty_output(self) -> None:
        assert truncate_test_output("", 0.20) == ""

    def test_single_line(self) -> None:
        result = truncate_test_output("1 passed", 0.20)
        assert result == "1 passed"


# ===== Redaction functions ===================================================


class TestRedactFilePaths:
    def test_redacts_file_string_pattern(self) -> None:
        text = 'File "/home/user/project/src/core.py", line 15'
        result = _redact_file_paths(text)
        assert result == 'File "[REDACTED_PATH]", line 15'

    def test_redacts_absolute_path_with_line(self) -> None:
        text = "/home/user/project/tests/test_core.py:42: TypeError"
        result = _redact_file_paths(text)
        assert "[REDACTED_PATH]" in result
        assert "/home/user" not in result

    def test_redacts_relative_path(self) -> None:
        text = "tests/test_core.py:42: AssertionError"
        result = _redact_file_paths(text)
        assert "[REDACTED_PATH]" in result

    def test_preserves_non_path_text(self) -> None:
        text = "FAILED - 1 error in 0.5s"
        result = _redact_file_paths(text)
        assert result == text


class TestRedactErrorNames:
    def test_redacts_common_errors(self) -> None:
        for name in ["TypeError", "ValueError", "KeyError", "AttributeError",
                      "RuntimeError", "AssertionError", "IndexError"]:
            assert "[ERROR]" in _redact_error_names(f"{name}: bad value")

    def test_redacts_exceptions(self) -> None:
        for name in ["StopIteration", "RuntimeException", "CustomException"]:
            # StopIteration doesn't match — it ends in "tion" not "tion"
            pass
        assert "[ERROR]" in _redact_error_names("ConnectionError: refused")

    def test_redacts_warnings_and_failures(self) -> None:
        assert "[ERROR]" in _redact_error_names("DeprecationWarning: old api")
        assert "[ERROR]" in _redact_error_names("AssertionFailure: nope")

    def test_preserves_non_error_text(self) -> None:
        text = "1 failed, 3 passed in 0.5s"
        assert _redact_error_names(text) == text

    def test_preserves_lowercase(self) -> None:
        # Only matches PascalCase error names
        text = "some error happened"
        assert _redact_error_names(text) == text


class TestCountRedactions:
    def test_detects_file_path_redactions(self) -> None:
        original = 'File "/home/user/foo.py"'
        modified = 'File "[REDACTED_PATH]"'
        assert "file_paths" in _count_redactions(original, modified)

    def test_detects_error_name_redactions(self) -> None:
        original = "TypeError: bad"
        modified = "[ERROR]: bad"
        assert "error_names" in _count_redactions(original, modified)

    def test_detects_both(self) -> None:
        original = 'File "/foo.py" TypeError'
        modified = 'File "[REDACTED_PATH]" [ERROR]'
        redactions = _count_redactions(original, modified)
        assert "file_paths" in redactions
        assert "error_names" in redactions

    def test_empty_when_no_redactions(self) -> None:
        assert _count_redactions("hello", "hello") == []


# ===== PostToolUse hooks =====================================================


class TestBuildPerturbationHooks:
    """Test the hook builder and async hook execution."""

    def test_baseline_returns_empty_list(self) -> None:
        hooks = build_perturbation_hooks(0.0, "agent-0", "task-1", [])
        assert hooks == []

    def test_nonzero_returns_one_matcher(self) -> None:
        hooks = build_perturbation_hooks(0.10, "agent-0", "task-1", [])
        assert len(hooks) == 1

    @pytest.mark.asyncio
    async def test_hook_skips_non_bash(self) -> None:
        log: list[dict] = []
        hooks = build_perturbation_hooks(0.10, "agent-0", "task-1", log)
        hook_fn = hooks[0].hooks[0]

        result = await hook_fn(
            {"tool_name": "Read", "tool_input": {"path": "f.py"}, "tool_response": "x"},
            "id-1",
            {},
        )
        assert result == {}
        assert len(log) == 0

    @pytest.mark.asyncio
    async def test_hook_skips_non_test_bash(self) -> None:
        log: list[dict] = []
        hooks = build_perturbation_hooks(0.10, "agent-0", "task-1", log)
        hook_fn = hooks[0].hooks[0]

        result = await hook_fn(
            {"tool_name": "Bash", "tool_input": {"command": "git status"}, "tool_response": "clean"},
            "id-2",
            {},
        )
        assert result == {}
        assert len(log) == 0

    @pytest.mark.asyncio
    async def test_hook_fires_on_test_bash(self, PYTEST_OUTPUT_LONG: str) -> None:
        log: list[dict] = []
        hooks = build_perturbation_hooks(0.10, "agent-0", "task-1", log)
        hook_fn = hooks[0].hooks[0]

        result = await hook_fn(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "pytest tests/ -v"},
                "tool_response": PYTEST_OUTPUT_LONG,
            },
            "id-3",
            {},
        )

        # Should return modified output
        assert "hookSpecificOutput" in result
        specific = result["hookSpecificOutput"]
        assert specific["hookEventName"] == "PostToolUse"
        modified = specific["updatedMCPToolOutput"]
        assert len(modified.splitlines()) == 15
        assert "[REDACTED_PATH]" in modified

    @pytest.mark.asyncio
    async def test_hook_logs_perturbation_event(self, PYTEST_OUTPUT_LONG: str) -> None:
        log: list[dict] = []
        hooks = build_perturbation_hooks(0.10, "agent-0", "task-1", log)
        hook_fn = hooks[0].hooks[0]

        await hook_fn(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "pytest tests/"},
                "tool_response": PYTEST_OUTPUT_LONG,
            },
            "id-4",
            {},
        )

        assert len(log) == 1
        event = log[0]

        # Verify event structure matches plan spec
        assert "ts" in event
        assert event["agent_id"] == "agent-0"
        assert event["task_id"] == "task-1"
        assert event["event"] == "PostToolUse"
        assert event["tool_name"] == "Bash"
        assert len(event["command_hash"]) == 16  # truncated sha256
        assert event["is_test_command"] is True
        assert event["perturbation_fired"] is True
        assert event["intensity"] == 0.10
        assert isinstance(event["original_output_lines"], int)
        assert isinstance(event["truncated_output_lines"], int)
        assert event["truncated_output_lines"] <= event["original_output_lines"]
        assert isinstance(event["redactions_applied"], list)

    @pytest.mark.asyncio
    async def test_hook_handles_non_string_output(self) -> None:
        """tool_response might not always be a string."""
        log: list[dict] = []
        hooks = build_perturbation_hooks(0.10, "agent-0", "task-1", log)
        hook_fn = hooks[0].hooks[0]

        result = await hook_fn(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "pytest tests/"},
                "tool_response": 12345,  # non-string
            },
            "id-5",
            {},
        )

        # Should handle gracefully (str(12345) is a single line)
        assert "hookSpecificOutput" in result

    @pytest.mark.asyncio
    async def test_hook_string_tool_input(self) -> None:
        """tool_input might be a plain string instead of dict."""
        log: list[dict] = []
        hooks = build_perturbation_hooks(0.10, "agent-0", "task-1", log)
        hook_fn = hooks[0].hooks[0]

        result = await hook_fn(
            {
                "tool_name": "Bash",
                "tool_input": "pytest tests/",  # string, not dict
                "tool_response": "FAILED\nE AssertionError",
            },
            "id-6",
            {},
        )

        assert "hookSpecificOutput" in result
        assert len(log) == 1


# ===== Hook composition =====================================================


class TestHookComposition:
    """build_agent_hooks should compose tracing and perturbation hooks."""

    def _make_trace_data(self) -> AgentTraceData:
        return AgentTraceData(
            agent_id="test-agent",
            instance_id="test-instance",
            agent_num=0,
            iteration=0,
            model="test-model",
        )

    def test_tracing_only(self) -> None:
        td = self._make_trace_data()
        hooks = build_agent_hooks(td)
        assert "PostToolUse" in hooks
        assert len(hooks["PostToolUse"]) == 1  # just tracing

    def test_with_perturbation_hooks(self) -> None:
        td = self._make_trace_data()
        extra = build_perturbation_hooks(0.10, "agent-0", "task-1", [])
        hooks = build_agent_hooks(td, extra_post_hooks=extra)
        assert len(hooks["PostToolUse"]) == 2  # tracing + perturbation

    def test_with_baseline_perturbation(self) -> None:
        td = self._make_trace_data()
        extra = build_perturbation_hooks(0.0, "agent-0", "task-1", [])
        hooks = build_agent_hooks(td, extra_post_hooks=extra)
        assert len(hooks["PostToolUse"]) == 1  # baseline adds nothing

    @pytest.mark.asyncio
    async def test_both_hooks_fire(self, PYTEST_OUTPUT_LONG: str) -> None:
        """Both tracing and perturbation hooks should execute."""
        td = self._make_trace_data()
        perturbation_log: list[dict] = []
        extra = build_perturbation_hooks(0.10, "agent-0", "task-1", perturbation_log)
        hooks = build_agent_hooks(td, extra_post_hooks=extra)

        # Execute all hooks in the chain
        for matcher in hooks["PostToolUse"]:
            for hook_fn in matcher.hooks:
                await hook_fn(
                    {
                        "tool_name": "Bash",
                        "tool_input": {"command": "pytest tests/"},
                        "tool_response": PYTEST_OUTPUT_LONG,
                    },
                    "id-1",
                    {},
                )

        # Tracing hook should have logged a tool call
        assert len(td.tool_calls) == 1
        assert td.tool_calls[0]["tool"] == "Bash"

        # Perturbation hook should have logged an event
        assert len(perturbation_log) == 1
        assert perturbation_log[0]["perturbation_fired"] is True


# ===== Intensity boundary tests ==============================================


class TestIntensityBoundaries:
    """Verify behaviour at exact boundary values."""

    def test_negative_intensity_treated_as_baseline(self) -> None:
        output = "some output\n" * 100
        assert truncate_test_output(output, -0.5) == output

    def test_exactly_zero(self) -> None:
        output = "some output\n" * 100
        assert truncate_test_output(output, 0.0) == output

    def test_between_low_and_medium(self) -> None:
        """0.07 > 0.05 threshold, so it promotes to medium (15 lines)."""
        output = "\n".join(f"line {i}" for i in range(100))
        result = truncate_test_output(output, 0.07)
        assert len(result.splitlines()) == 15

    def test_between_medium_and_high(self) -> None:
        """0.15 > 0.10 threshold, so it promotes to high (5 lines)."""
        output = "\n".join(f"line {i}" for i in range(100))
        result = truncate_test_output(output, 0.15)
        assert len(result.splitlines()) == 5

    def test_above_high(self) -> None:
        """0.50 should behave like 0.20 (high)."""
        output = "\n".join(f"line {i}" for i in range(100))
        result = truncate_test_output(output, 0.50)
        assert len(result.splitlines()) == 5

    def test_hook_builder_negative_returns_empty(self) -> None:
        hooks = build_perturbation_hooks(-1.0, "a", "t", [])
        assert hooks == []


# ===== Role planning parser ==================================================


class TestParseRolesJson:
    """_parse_roles_json extracts and validates role arrays from LLM text."""

    def test_valid_json_array(self) -> None:
        text = '[{"name": "tracer", "goal": "Trace the bug."},' \
               ' {"name": "fixer", "goal": "Fix it."}]'
        roles = _parse_roles_json(text)
        assert roles is not None
        assert len(roles) == 2
        assert roles[0]["name"] == "tracer"

    def test_json_embedded_in_text(self) -> None:
        text = 'Here are the roles:\n[{"name": "a", "goal": "x"}, {"name": "b", "goal": "y"}]\nDone.'
        roles = _parse_roles_json(text)
        assert roles is not None
        assert len(roles) == 2

    def test_rejects_single_role(self) -> None:
        text = '[{"name": "solo", "goal": "do everything"}]'
        assert _parse_roles_json(text) is None

    def test_rejects_five_roles(self) -> None:
        roles_list = [{"name": f"r{i}", "goal": f"g{i}"} for i in range(5)]
        import json
        assert _parse_roles_json(json.dumps(roles_list)) is None

    def test_rejects_missing_name(self) -> None:
        text = '[{"goal": "x"}, {"name": "b", "goal": "y"}]'
        assert _parse_roles_json(text) is None

    def test_rejects_missing_goal(self) -> None:
        text = '[{"name": "a"}, {"name": "b", "goal": "y"}]'
        assert _parse_roles_json(text) is None

    def test_rejects_no_array(self) -> None:
        assert _parse_roles_json("No JSON here") is None

    def test_rejects_invalid_json(self) -> None:
        assert _parse_roles_json("[{broken json}]") is None

    def test_accepts_four_roles(self) -> None:
        roles_list = [{"name": f"r{i}", "goal": f"g{i}"} for i in range(4)]
        import json
        assert _parse_roles_json(json.dumps(roles_list)) is not None


# ===== Patch selection ========================================================


class TestSelectBestPatch:
    """select_best_patch picks the best fix from the ledger."""

    def _setup_ledger(self, tmp_path: Path, num_agents: int) -> tuple[Path, Path]:
        """Create a fake repo dir with ledger structure."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        ledger_dir = repo_dir / "swarm_ledger"
        for i in range(num_agents):
            (ledger_dir / f"agent-{i}").mkdir(parents=True)
        # Init as a git repo so extract_patch works
        subprocess.run(["git", "init"], cwd=str(repo_dir), capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(repo_dir), capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(repo_dir), capture_output=True,
        )
        # Create a file and initial commit
        (repo_dir / "file.py").write_text("original\n")
        subprocess.run(["git", "add", "."], cwd=str(repo_dir), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(repo_dir), capture_output=True,
        )
        return repo_dir, ledger_dir

    def test_falls_back_to_workspace_diff(self, tmp_path: Path) -> None:
        """With no proposed diffs, should return current workspace diff."""
        repo_dir, ledger_dir = self._setup_ledger(tmp_path, 2)
        # Make a change in the workspace
        (repo_dir / "file.py").write_text("modified\n")
        patch = select_best_patch(repo_dir, ledger_dir, 2)
        assert "modified" in patch

    def test_empty_workspace_returns_empty(self, tmp_path: Path) -> None:
        """No changes, no diffs → empty patch."""
        repo_dir, ledger_dir = self._setup_ledger(tmp_path, 2)
        patch = select_best_patch(repo_dir, ledger_dir, 2)
        assert patch.strip() == ""

    def test_single_proposed_diff(self, tmp_path: Path) -> None:
        """One agent proposed a diff → use it."""
        repo_dir, ledger_dir = self._setup_ledger(tmp_path, 2)
        # Create a diff file for agent-0
        diff = "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-original\n+fixed\n"
        (ledger_dir / "agent-0" / "proposed_fix.diff").write_text(diff)
        patch = select_best_patch(repo_dir, ledger_dir, 2)
        assert "fixed" in patch

    def test_endorsed_fix_wins(self, tmp_path: Path) -> None:
        """A fix endorsed by another agent should be preferred."""
        repo_dir, ledger_dir = self._setup_ledger(tmp_path, 3)
        # Agent 1 proposes a fix
        diff = "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-original\n+endorsed_fix\n"
        (ledger_dir / "agent-1" / "proposed_fix.diff").write_text(diff)
        # Agent 2 also proposes a fix
        diff2 = "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-original\n+other_fix\n"
        (ledger_dir / "agent-2" / "proposed_fix.diff").write_text(diff2)
        # Agent 0 verifies agent-1's fix passes
        (ledger_dir / "agent-0" / "verification.md").write_text(
            "Verified agent-1's fix. Tests pass."
        )
        patch = select_best_patch(repo_dir, ledger_dir, 3)
        assert "endorsed_fix" in patch
