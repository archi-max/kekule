"""Tests for oracle Docker runner."""

import shutil

import pytest

from kekule.oracle.runner import (
    _detect_install_commands,
    _generate_dockerfile,
    _generate_dockerignore,
)
from kekule.oracle.schemas import OracleResult, OracleRunRequest, Rule

pytestmark_docker = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="Docker not available",
)


class TestDetectInstallCommands:
    def test_detects_pyproject_toml(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
        cmds = _detect_install_commands(tmp_path)
        assert len(cmds) == 1
        assert "pip install" in cmds[0]
        assert "." in cmds[0]

    def test_detects_requirements_txt(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("requests\nflask\n")
        cmds = _detect_install_commands(tmp_path)
        assert len(cmds) == 1
        assert "requirements.txt" in cmds[0]

    def test_detects_setup_py(self, tmp_path):
        (tmp_path / "setup.py").write_text(
            "from setuptools import setup\nsetup()"
        )
        cmds = _detect_install_commands(tmp_path)
        assert len(cmds) == 1
        assert "pip install" in cmds[0]

    def test_no_deps_file(self, tmp_path):
        cmds = _detect_install_commands(tmp_path)
        assert len(cmds) == 0

    def test_pyproject_takes_priority_over_requirements(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
        (tmp_path / "requirements.txt").write_text("requests\n")
        cmds = _detect_install_commands(tmp_path)
        # Should use pyproject.toml, not requirements.txt
        assert len(cmds) == 1
        assert "." in cmds[0]
        assert "requirements.txt" not in cmds[0]


class TestGenerateDockerfile:
    def test_dockerfile_has_base_image(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        oracle_dir = tmp_path / "oracle"
        oracle_dir.mkdir()

        content = _generate_dockerfile(repo_dir, oracle_dir, "python:3.11-slim")
        assert "FROM python:3.11-slim" in content

    def test_dockerfile_installs_pytest(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        oracle_dir = tmp_path / "oracle"
        oracle_dir.mkdir()

        content = _generate_dockerfile(repo_dir, oracle_dir)
        assert "pip install" in content
        assert "pytest" in content

    def test_dockerfile_copies_repo(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        oracle_dir = tmp_path / "oracle"
        oracle_dir.mkdir()

        content = _generate_dockerfile(repo_dir, oracle_dir)
        assert "COPY repo/" in content

    def test_dockerfile_copies_oracle_tests(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        oracle_dir = tmp_path / "oracle"
        oracle_dir.mkdir()

        content = _generate_dockerfile(repo_dir, oracle_dir)
        assert "COPY oracle_tests/" in content

    def test_dockerfile_runs_pytest(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        oracle_dir = tmp_path / "oracle"
        oracle_dir.mkdir()

        content = _generate_dockerfile(repo_dir, oracle_dir)
        assert "pytest" in content
        assert "/workspace/oracle_tests/" in content

    def test_dockerfile_with_requirements(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        (repo_dir / "requirements.txt").write_text("requests\n")
        oracle_dir = tmp_path / "oracle"
        oracle_dir.mkdir()

        content = _generate_dockerfile(repo_dir, oracle_dir)
        assert "requirements.txt" in content

    def test_custom_base_image(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        oracle_dir = tmp_path / "oracle"
        oracle_dir.mkdir()

        content = _generate_dockerfile(
            repo_dir, oracle_dir, "python:3.12-bookworm"
        )
        assert "FROM python:3.12-bookworm" in content


class TestGenerateDockerignore:
    def test_excludes_git(self):
        content = _generate_dockerignore()
        assert ".git/" in content

    def test_excludes_pycache(self):
        content = _generate_dockerignore()
        assert "__pycache__/" in content

    def test_excludes_venv(self):
        content = _generate_dockerignore()
        assert ".venv/" in content

    def test_excludes_node_modules(self):
        content = _generate_dockerignore()
        assert "node_modules/" in content
