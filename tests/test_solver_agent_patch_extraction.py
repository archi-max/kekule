import subprocess
from pathlib import Path

from kekule.benchmarks.solver_agent import extract_patch


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


def test_extract_patch_filters_noisy_docicons_hunks(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    src_file = repo / "src" / "app.py"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text("print('old')\n")

    noisy_file = repo / "docs" / "_theme" / "djangodocs-epub" / "static" / "docicons-icon"
    noisy_file.parent.mkdir(parents=True, exist_ok=True)
    noisy_file.symlink_to("target-icon")

    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "init"], repo)

    src_file.write_text("print('new')\n")
    noisy_file.unlink()
    noisy_file.write_text("not-a-symlink-anymore\n")

    patch = extract_patch(repo)

    assert "src/app.py" in patch
    assert "docicons-icon" not in patch


def test_extract_patch_rejects_non_noisy_symlink_patch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    target = repo / "src" / "target.txt"
    link = repo / "src" / "link.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("target\n")
    link.write_text("regular\n")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "init"], repo)

    link.unlink()
    link.symlink_to("target.txt")

    patch = extract_patch(repo)

    assert patch == ""
