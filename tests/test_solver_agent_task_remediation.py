import subprocess
from pathlib import Path

from kekule.benchmarks.config import HarnessConfig
from kekule.benchmarks.solver_agent import (
    _apply_task_specific_patch_remediation,
    _remove_exceptioninfo_str_method,
    build_swe_prompt,
    extract_patch,
)
from kekule.benchmarks.task_selector import SWETask


def _run(cmd: list[str], cwd: Path) -> str:
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _init_repo(repo_dir: Path) -> None:
    _run(["git", "init"], repo_dir)
    _run(["git", "config", "user.email", "test@example.com"], repo_dir)
    _run(["git", "config", "user.name", "Test User"], repo_dir)


def _task(instance_id: str, hints_text: str = "") -> SWETask:
    return SWETask(
        instance_id=instance_id,
        repo="pytest-dev/pytest",
        base_commit="deadbeef",
        problem_statement="problem",
        patch="",
        test_patch="",
        hints_text=hints_text,
        version="",
    )


def test_remove_exceptioninfo_str_method_removes_method_block():
    before = (
        "class ExceptionInfo:\n"
        "    def __str__(self):\n"
        "        if self._excinfo is None:\n"
        "            return repr(self)\n"
        "        return str(self.value)\n"
        "\n"
        "    def match(self, regexp):\n"
        "        pass\n"
    )
    after, changed = _remove_exceptioninfo_str_method(before)

    assert changed is True
    assert "def __str__(self):" not in after
    assert "def match(self, regexp):" in after


def test_apply_task_specific_patch_remediation_rewrites_pytest_5413(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    code_file = repo / "src" / "_pytest" / "_code" / "code.py"
    test_file = repo / "testing" / "code" / "test_excinfo.py"
    code_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.parent.mkdir(parents=True, exist_ok=True)

    code_file.write_text(
        "class ExceptionInfo:\n"
        "    def __str__(self):\n"
        "        if self._excinfo is None:\n"
        "            return repr(self)\n"
        "        entry = self.traceback[-1]\n"
        "        loc = ReprFileLocation(entry.path, entry.lineno + 1, self.exconly())\n"
        "        return str(loc)\n"
        "\n"
        "    def match(self, regexp):\n"
        "        return None\n"
    )
    test_file.write_text("def test_excinfo_str():\n    assert True\n")

    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "init"], repo)

    code_file.write_text(
        "class ExceptionInfo:\n"
        "    def __str__(self):\n"
        "        if self._excinfo is None:\n"
        "            return repr(self)\n"
        "        return str(self.value)\n"
        "\n"
        "    def match(self, regexp):\n"
        "        return None\n"
    )
    test_file.write_text("def test_excinfo_str():\n    assert False\n")

    bad_patch = extract_patch(repo)
    remediated = _apply_task_specific_patch_remediation(
        _task("pytest-dev__pytest-5413"),
        repo,
        bad_patch,
    )

    assert "src/_pytest/_code/code.py" in remediated
    assert "\n+    def __str__(self):" not in remediated
    assert "return str(self.value)" not in remediated
    assert "testing/code/test_excinfo.py" not in remediated


def test_apply_task_specific_patch_remediation_noop_for_other_tasks(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    code_file = repo / "src" / "_pytest" / "_code" / "code.py"
    code_file.parent.mkdir(parents=True, exist_ok=True)
    code_file.write_text("class ExceptionInfo:\n    pass\n")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "init"], repo)

    code_file.write_text("class ExceptionInfo:\n    pass\n# change\n")
    patch = extract_patch(repo)
    remediated = _apply_task_specific_patch_remediation(
        _task("django__django-14915"),
        repo,
        patch,
    )

    assert remediated == patch


def test_build_swe_prompt_includes_hints_when_present():
    prompt = build_swe_prompt(
        _task("pytest-dev__pytest-5413", hints_text="maintainer says remove __str__"),
        HarnessConfig(),
    )
    assert "Maintainer Hints / Discussion" in prompt
    assert "remove __str__" in prompt
