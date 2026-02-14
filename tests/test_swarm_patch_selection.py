import subprocess
from pathlib import Path

from kekule.benchmarks.solvers.perturbation_swarm import (
    _ensure_agent_proposed_diff,
    _score_verification_for_agent,
    select_best_patch,
)


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


def test_select_best_patch_applies_sanitized_candidate(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    src_file = repo / "src" / "app.py"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text("print('old')\n")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "init"], repo)

    src_file.write_text("print('new')\n")
    patch = _run(["git", "diff", "--no-ext-diff", "--binary"], repo)
    _run(["git", "checkout", "--", "."], repo)

    ledger = repo / "swarm_ledger" / "agent-0"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "proposed_fix.diff").write_text(patch)
    (ledger / "verification.md").write_text("agent-0 PASS")

    selected = select_best_patch(repo, repo / "swarm_ledger", num_agents=1)

    assert "src/app.py" in selected
    assert "print('new')" in selected


def test_select_best_patch_fallback_drops_noisy_docicons_changes(tmp_path):
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

    ledger = repo / "swarm_ledger"
    (ledger / "agent-0").mkdir(parents=True, exist_ok=True)
    selected = select_best_patch(repo, ledger, num_agents=1)

    assert "src/app.py" in selected
    assert "docicons-icon" not in selected


def test_ensure_agent_proposed_diff_backfills_missing_diff(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    src_file = repo / "src" / "app.py"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text("print('old')\n")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "init"], repo)

    src_file.write_text("print('new')\n")
    ledger = repo / "swarm_ledger" / "agent-0"
    ledger.mkdir(parents=True, exist_ok=True)

    _ensure_agent_proposed_diff(repo, repo / "swarm_ledger", 0)

    proposed = (ledger / "proposed_fix.diff").read_text()
    assert "src/app.py" in proposed
    assert "print('new')" in proposed


def test_select_best_patch_prefers_higher_verification_score(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    src_file = repo / "src" / "app.py"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text("print('base')\n")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "init"], repo)

    src_file.write_text("print('agent0')\n")
    patch0 = _run(["git", "diff", "--no-ext-diff", "--binary"], repo)
    _run(["git", "checkout", "--", "."], repo)

    src_file.write_text("print('agent1')\n")
    patch1 = _run(["git", "diff", "--no-ext-diff", "--binary"], repo)
    _run(["git", "checkout", "--", "."], repo)

    ledger = repo / "swarm_ledger"
    (ledger / "agent-0").mkdir(parents=True, exist_ok=True)
    (ledger / "agent-1").mkdir(parents=True, exist_ok=True)
    (ledger / "agent-0" / "proposed_fix.diff").write_text(patch0)
    (ledger / "agent-1" / "proposed_fix.diff").write_text(patch1)
    (ledger / "agent-0" / "verification.md").write_text("agent-1 pass")
    (ledger / "agent-1" / "verification.md").write_text("agent-0 fail")

    selected = select_best_patch(repo, ledger, num_agents=2)

    assert "print('agent1')" in selected
    assert "print('agent0')" not in selected


def test_score_verification_for_agent_counts_pass_and_fail():
    verification = """
    checked agent-2 PASS on local run
    agent-2 failed after rebase
    unrelated note for agent-1 pass
    """
    score = _score_verification_for_agent(verification, agent_num=2)
    assert score == 0
