"""
CLI entry point for the Oracle Generator.

Usage:
    python -m kekule.oracle generate --rules rules.json --repo /path/to/repo
    python -m kekule.oracle run --rules rules.json --repo /path/to/repo --commit abc123
    python -m kekule.oracle elicit --repo /path/to/repo
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from .agent import generate_all_oracles
from .elicitor import load_rules_from_file
from .elicitor.pipeline import run_elicitation
from .runner import run_oracles
from .schemas import OracleResult, OracleRunRequest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Kekule Oracle Generator -- verification artifact generation and execution",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- generate ---
    gen_parser = subparsers.add_parser(
        "generate",
        help="Generate pytest oracle artifacts from rules",
    )
    gen_parser.add_argument(
        "--rules", type=str, required=True, help="Path to rules JSON file"
    )
    gen_parser.add_argument(
        "--repo", type=str, required=True, help="Path to local repository"
    )
    gen_parser.add_argument(
        "--output-dir", type=str, default=None, help="Output directory for artifacts"
    )
    gen_parser.add_argument(
        "--model",
        type=str,
        default="claude-sonnet-4-5",
        help="Model for oracle generation",
    )
    gen_parser.add_argument(
        "--max-turns", type=int, default=30, help="Max agent turns per oracle"
    )
    gen_parser.add_argument(
        "--max-parallel",
        type=int,
        default=3,
        help="Max parallel oracle generations",
    )

    # --- run ---
    run_parser = subparsers.add_parser(
        "run",
        help="Generate + run oracles in Docker (end-to-end)",
    )
    run_parser.add_argument(
        "--rules", type=str, required=True, help="Path to rules JSON file"
    )
    run_parser.add_argument(
        "--repo",
        type=str,
        required=True,
        help="Path to local repo OR git URL",
    )
    run_parser.add_argument(
        "--commit",
        type=str,
        default=None,
        help="Git commit SHA (required for remote repos)",
    )
    run_parser.add_argument(
        "--docker-image",
        type=str,
        default="python:3.11-slim",
        help="Base Docker image",
    )
    run_parser.add_argument(
        "--timeout", type=int, default=300, help="Container timeout in seconds"
    )
    run_parser.add_argument(
        "--output-dir", type=str, default=None, help="Output directory for artifacts"
    )
    run_parser.add_argument(
        "--model",
        type=str,
        default="claude-sonnet-4-5",
        help="Model for oracle generation",
    )
    run_parser.add_argument(
        "--max-parallel", type=int, default=3, help="Max parallelism"
    )

    # --- elicit ---
    elicit_parser = subparsers.add_parser(
        "elicit",
        help="Interactively elicit rules via Claude Agent SDK",
    )
    elicit_parser.add_argument(
        "--repo", type=str, required=True, help="Path to local repository"
    )
    elicit_parser.add_argument(
        "--intent",
        type=str,
        default="",
        help="Initial description of what to verify",
    )
    elicit_parser.add_argument(
        "--model",
        type=str,
        default="claude-sonnet-4-5",
        help="Model for elicitation",
    )
    elicit_parser.add_argument(
        "--output", type=str, default=None, help="Output file for rules JSON"
    )

    return parser.parse_args()


async def cmd_generate(args: argparse.Namespace) -> None:
    """Handle the 'generate' subcommand."""
    rules = load_rules_from_file(args.rules)
    logger.info(f"Loaded {len(rules)} rules from {args.rules}")

    artifact_paths = await generate_all_oracles(
        rules=rules,
        repo_path=args.repo,
        output_dir=args.output_dir,
        model=args.model,
        max_turns=args.max_turns,
        max_parallel=args.max_parallel,
    )

    print(f"\nGenerated {len(artifact_paths)} oracle artifacts:")
    for rule_id, path in artifact_paths.items():
        print(f"  [{rule_id}] -> {path}")


async def cmd_run(args: argparse.Namespace) -> None:
    """Handle the 'run' subcommand -- generate + execute in Docker."""
    rules = load_rules_from_file(args.rules)
    logger.info(f"Loaded {len(rules)} rules from {args.rules}")

    is_url = args.repo.startswith(("http://", "https://", "git@"))

    # Step 1: Generate artifacts
    # For remote repos, we need a local copy for the agent to explore
    if is_url:
        import subprocess
        import tempfile

        if not args.commit:
            logger.error("--commit is required when using a remote repo URL")
            sys.exit(1)

        clone_dir = Path(tempfile.mkdtemp(prefix="kekule-oracle-gen-"))
        logger.info(f"Cloning {args.repo} for oracle generation...")
        subprocess.run(
            ["git", "clone", "--quiet", args.repo, str(clone_dir)],
            check=True,
            capture_output=True,
            timeout=600,
        )
        subprocess.run(
            ["git", "checkout", "-f", args.commit],
            cwd=str(clone_dir),
            check=True,
            capture_output=True,
            timeout=300,
        )
        gen_repo_path = clone_dir
    else:
        gen_repo_path = Path(args.repo)

    artifact_paths = await generate_all_oracles(
        rules=rules,
        repo_path=gen_repo_path,
        output_dir=args.output_dir,
        model=args.model,
        max_parallel=args.max_parallel,
    )

    if not artifact_paths:
        logger.error("No oracle artifacts were generated. Aborting.")
        sys.exit(1)

    print(f"\nGenerated {len(artifact_paths)} oracle artifacts")

    # Step 2: Run in Docker
    request = OracleRunRequest(
        repo_url=args.repo if is_url else None,
        repo_path=args.repo if not is_url else None,
        git_commit=args.commit,
        rules=rules,
        docker_image=args.docker_image,
        timeout_s=args.timeout,
    )

    results = await run_oracles(
        request=request,
        artifact_paths=artifact_paths,
        max_parallel=args.max_parallel,
    )

    _print_results(results)

    # Exit with non-zero if any oracle failed
    if any(not r.passed for r in results):
        sys.exit(1)


async def cmd_elicit(args: argparse.Namespace) -> None:
    """Handle the 'elicit' subcommand -- 3-phase pipeline."""
    rules = await run_elicitation(
        repo_path=args.repo,
        model=args.model,
    )

    rules_data = {"rules": [r.model_dump() for r in rules]}

    if args.output:
        with open(args.output, "w") as f:
            json.dump(rules_data, f, indent=2)
        print(f"\nWrote {len(rules)} rules to {args.output}")
    else:
        print(json.dumps(rules_data, indent=2))


def _print_results(results: list[OracleResult]) -> None:
    """Print oracle results summary."""
    print("\n" + "=" * 60)
    print("ORACLE RESULTS")
    print("=" * 60)

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        print(
            f"  [{mark}] {r.rule_id} "
            f"(exit_code={r.exit_code}, {r.execution_time_s:.1f}s)"
        )
        if not r.passed and r.evidence:
            lines = r.evidence.strip().split("\n")
            for line in lines[-10:]:
                print(f"         {line}")

    print(f"\nTotal: {len(results)} | Passed: {passed} | Failed: {failed}")
    print("=" * 60)


def main() -> None:
    """CLI entry point."""
    args = parse_args()
    if args.command == "generate":
        asyncio.run(cmd_generate(args))
    elif args.command == "run":
        asyncio.run(cmd_run(args))
    elif args.command == "elicit":
        asyncio.run(cmd_elicit(args))


if __name__ == "__main__":
    main()
