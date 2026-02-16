"""
Docker Runner -- executes oracle artifacts in isolated containers.

Builds a Docker image with the repo + oracle tests, runs pytest
inside the container, and collects exit codes + output as OracleResult.
"""

import asyncio
import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .schemas import OracleResult, OracleRunRequest, Rule

logger = logging.getLogger(__name__)


def _detect_install_commands(repo_path: Path) -> list[str]:
    """Detect how to install the project's dependencies.

    Checks for (in priority order):
    1. pyproject.toml with [project] -> pip install .
    2. requirements.txt -> pip install -r requirements.txt
    3. setup.py -> pip install .
    4. None found -> no extra install commands

    Uses non-editable installs since Docker containers don't
    benefit from editable mode.

    Args:
        repo_path: Path to the repository root.

    Returns:
        List of RUN commands for the Dockerfile (without the RUN prefix).
    """
    if (repo_path / "pyproject.toml").exists():
        return ["pip install --no-cache-dir ."]
    if (repo_path / "requirements.txt").exists():
        return ["pip install --no-cache-dir -r requirements.txt"]
    if (repo_path / "setup.py").exists():
        return ["pip install --no-cache-dir ."]
    return []


def _generate_dockerfile(
    repo_path: Path,
    oracle_dir: Path,
    base_image: str = "python:3.11-slim",
) -> str:
    """Generate a Dockerfile for oracle execution.

    The image contains the repo code, oracle test files, and all
    dependencies needed to run pytest.

    Args:
        repo_path: Path to the repo (used to detect dependencies).
        oracle_dir: Path to the oracle test artifacts.
        base_image: Base Docker image.

    Returns:
        Dockerfile content as a string.
    """
    install_cmds = _detect_install_commands(repo_path)
    install_lines = "\n".join(f"RUN {cmd}" for cmd in install_cmds)
    if install_lines:
        install_lines = "\n# Install project dependencies\n" + install_lines

    return f"""FROM {base_image}

WORKDIR /workspace

# Copy the repository
COPY repo/ /workspace/

# Install pytest
RUN pip install --no-cache-dir pytest
{install_lines}
# Copy oracle test files
COPY oracle_tests/ /workspace/oracle_tests/

# Run tests
CMD ["python", "-m", "pytest", "/workspace/oracle_tests/", "--tb=short", "-v", "--no-header"]
"""


def _generate_dockerignore() -> str:
    """Generate a .dockerignore to exclude unnecessary files."""
    return """.git/
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.mypy_cache/
.ruff_cache/
node_modules/
.venv/
venv/
*.egg-info/
dist/
build/
.tox/
"""


def _prepare_build_context(
    rule: Rule,
    artifact_path: Path,
    repo_path: Path,
    base_image: str,
) -> Path:
    """Create a Docker build context directory.

    Sets up a temporary directory with:
    - repo/ -- copy of the repository
    - oracle_tests/ -- the test file for this rule
    - Dockerfile -- generated Dockerfile
    - .dockerignore -- exclude unnecessary files

    Args:
        rule: The rule being verified.
        artifact_path: Path to the test file.
        repo_path: Path to the repository.
        base_image: Base Docker image.

    Returns:
        Path to the build context directory.
    """
    context_dir = Path(tempfile.mkdtemp(prefix=f"kekule-oracle-{rule.id}-"))

    # Copy repo (excluding .git for speed)
    repo_dest = context_dir / "repo"
    shutil.copytree(
        repo_path,
        repo_dest,
        ignore=shutil.ignore_patterns(
            ".git", "__pycache__", "*.pyc", "node_modules", ".venv", "venv"
        ),
    )

    # Copy oracle test file
    oracle_dest = context_dir / "oracle_tests"
    oracle_dest.mkdir()
    shutil.copy2(artifact_path, oracle_dest / artifact_path.name)

    # Write Dockerfile
    dockerfile = _generate_dockerfile(repo_path, oracle_dest, base_image)
    (context_dir / "Dockerfile").write_text(dockerfile)

    # Write .dockerignore
    (context_dir / ".dockerignore").write_text(_generate_dockerignore())

    return context_dir


def _prepare_repo(request: OracleRunRequest) -> Path:
    """Prepare the repository for Docker builds.

    If repo_url is provided, clones and checks out the specified commit.
    If repo_path is provided, uses it directly.

    Args:
        request: The run request with repo_url or repo_path.

    Returns:
        Path to the prepared repository.

    Raises:
        ValueError: If neither repo_url nor repo_path is provided.
        subprocess.CalledProcessError: If git operations fail.
    """
    if request.repo_path:
        repo = Path(request.repo_path)
        if not repo.exists():
            raise FileNotFoundError(f"Repository not found: {repo}")

        # If a commit is specified and we have a local repo, checkout that commit
        if request.git_commit:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(repo),
                capture_output=True,
                text=True,
            )
            current_head = result.stdout.strip() if result.returncode == 0 else ""
            if current_head != request.git_commit:
                logger.info(
                    f"Checking out commit {request.git_commit[:12]} in {repo}"
                )
                subprocess.run(
                    ["git", "checkout", "-f", request.git_commit],
                    cwd=str(repo),
                    check=True,
                    capture_output=True,
                    timeout=300,
                )
        return repo

    if request.repo_url:
        if not request.git_commit:
            raise ValueError("git_commit is required when using repo_url")

        clone_dir = Path(
            tempfile.mkdtemp(prefix="kekule-oracle-repo-")
        )
        logger.info(f"Cloning {request.repo_url} to {clone_dir}")
        subprocess.run(
            ["git", "clone", "--quiet", request.repo_url, str(clone_dir)],
            check=True,
            capture_output=True,
            timeout=600,
        )
        logger.info(f"Checking out commit {request.git_commit[:12]}")
        subprocess.run(
            ["git", "checkout", "-f", request.git_commit],
            cwd=str(clone_dir),
            check=True,
            capture_output=True,
            timeout=300,
        )
        return clone_dir

    raise ValueError("Either repo_url or repo_path must be provided")


def _check_docker_available() -> None:
    """Check that Docker is available and the daemon is running.

    Raises:
        RuntimeError: If Docker is not available or the daemon is not running.
    """
    if shutil.which("docker") is None:
        raise RuntimeError(
            "Docker is not installed. Install Docker to run oracle containers."
        )

    result = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Docker daemon is not accessible. "
            f"You may need to run: sudo chown root:docker /var/run/docker.sock\n"
            f"Error: {result.stderr.strip()}"
        )


async def _run_single_oracle(
    rule: Rule,
    artifact_path: Path,
    repo_path: Path,
    base_image: str,
    timeout_s: int,
) -> OracleResult:
    """Build and run a Docker container for a single oracle.

    Args:
        rule: The rule being verified.
        artifact_path: Path to the test file.
        repo_path: Path to the repository.
        base_image: Base Docker image.
        timeout_s: Container timeout in seconds.

    Returns:
        OracleResult with pass/fail, evidence, and timing.
    """
    start_time = time.time()
    ts = int(time.time())
    image_tag = f"kekule-oracle-{rule.id}:{ts}"
    context_dir = None

    try:
        # Prepare build context
        context_dir = await asyncio.to_thread(
            _prepare_build_context, rule, artifact_path, repo_path, base_image
        )

        # Build Docker image
        logger.info(f"[{rule.id}] Building Docker image {image_tag}...")
        build_result = await asyncio.to_thread(
            subprocess.run,
            ["docker", "build", "-t", image_tag, "."],
            cwd=str(context_dir),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if build_result.returncode != 0:
            elapsed = time.time() - start_time
            return OracleResult(
                rule_id=rule.id,
                passed=False,
                evidence=f"Docker build failed:\n{build_result.stderr}",
                artifact_path=str(artifact_path),
                execution_time_s=elapsed,
                exit_code=build_result.returncode,
            )

        # Run container
        logger.info(f"[{rule.id}] Running oracle container...")
        run_result = await asyncio.to_thread(
            subprocess.run,
            [
                "docker", "run", "--rm",
                "--network=none",
                "--memory=512m",
                "--cpus=1",
                image_tag,
            ],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )

        elapsed = time.time() - start_time
        passed = run_result.returncode == 0
        evidence = run_result.stdout
        if run_result.stderr:
            evidence += f"\n--- stderr ---\n{run_result.stderr}"

        logger.info(
            f"[{rule.id}] {'PASSED' if passed else 'FAILED'} "
            f"(exit_code={run_result.returncode}, time={elapsed:.1f}s)"
        )

        return OracleResult(
            rule_id=rule.id,
            passed=passed,
            evidence=evidence,
            artifact_path=str(artifact_path),
            execution_time_s=elapsed,
            exit_code=run_result.returncode,
        )

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        logger.error(f"[{rule.id}] Container timed out after {timeout_s}s")
        return OracleResult(
            rule_id=rule.id,
            passed=False,
            evidence=f"Container timed out after {timeout_s}s",
            artifact_path=str(artifact_path),
            execution_time_s=elapsed,
            exit_code=-1,
        )
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[{rule.id}] Unexpected error: {e}")
        return OracleResult(
            rule_id=rule.id,
            passed=False,
            evidence=f"Unexpected error: {e}",
            artifact_path=str(artifact_path),
            execution_time_s=elapsed,
            exit_code=-1,
        )
    finally:
        # Cleanup: remove Docker image
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["docker", "rmi", "-f", image_tag],
                capture_output=True,
                timeout=30,
            )
        except Exception:
            pass

        # Cleanup: remove build context
        if context_dir and context_dir.exists():
            try:
                shutil.rmtree(context_dir)
            except Exception:
                pass


async def run_oracles(
    request: OracleRunRequest,
    artifact_paths: dict[str, Path],
    max_parallel: int = 3,
) -> list[OracleResult]:
    """Run all oracle artifacts for a request in Docker containers.

    Each oracle runs in its own isolated container with network disabled
    and resource limits applied.

    Args:
        request: The run request (repo info, rules, Docker config).
        artifact_paths: Dict mapping rule_id -> path to test file.
        max_parallel: Max concurrent Docker containers.

    Returns:
        List of OracleResult, one per rule.
    """
    _check_docker_available()

    # Prepare repo
    repo_path = _prepare_repo(request)

    # Build rule lookup
    rules_by_id = {rule.id: rule for rule in request.rules}

    # Run oracles with concurrency control
    semaphore = asyncio.Semaphore(max_parallel)

    async def _run_with_limit(rule_id: str, artifact_path: Path) -> OracleResult:
        async with semaphore:
            rule = rules_by_id[rule_id]
            return await _run_single_oracle(
                rule=rule,
                artifact_path=artifact_path,
                repo_path=repo_path,
                base_image=request.docker_image,
                timeout_s=request.timeout_s,
            )

    tasks = [
        _run_with_limit(rule_id, path)
        for rule_id, path in artifact_paths.items()
        if rule_id in rules_by_id
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    oracle_results: list[OracleResult] = []
    for result in results:
        if isinstance(result, Exception):
            logger.error(f"Unexpected error running oracle: {result}")
            oracle_results.append(
                OracleResult(
                    rule_id="unknown",
                    passed=False,
                    evidence=str(result),
                    exit_code=-1,
                )
            )
        else:
            oracle_results.append(result)

    return oracle_results
