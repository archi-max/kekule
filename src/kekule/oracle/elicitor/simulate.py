"""
Simulation script -- runs the elicitation pipeline with pre-scripted
user inputs to validate the 3-phase flow end-to-end.

Two scenarios:
1. Clear intent: user knows exactly what they want verified
2. Vague intent: user is unclear, conversation agent must draw out specifics

Usage:
    python -m kekule.oracle.elicitor.simulate
    python -m kekule.oracle.elicitor.simulate --scenario 1
    python -m kekule.oracle.elicitor.simulate --scenario 2
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from .pipeline import run_elicitation

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Scenario 1: Clear intent ────────────────────────────────────
SCENARIO_1_RESPONSES = [
    # User knows what they want
    "I want to verify the core calculator operations - add, subtract, multiply, divide. "
    "Division by zero should raise an error. Also verify the temperature converter "
    "does correct roundtrip conversions (Celsius to Fahrenheit and back should give the same value).",

    # Follow-up clarification
    "Yes, those are the priorities. Division by zero is critical - it must raise "
    "ZeroDivisionError specifically. The roundtrip tolerance should be within 1e-9. "
    "I also want to make sure the statistics mean function works and handles empty lists.",

    # Done
    "done",
]

# ── Scenario 2: Vague intent ────────────────────────────────────
SCENARIO_2_RESPONSES = [
    # User is vague
    "Make sure the calculator doesn't break. I don't want users hitting errors.",

    # Agent should ask clarifying questions; user gives more info
    "Well, the math operations should give correct results obviously. And if someone "
    "tries to divide by zero it should handle that gracefully, not crash. I guess the "
    "converter should work too.",

    # Agent asks about priorities/specifics
    "The math stuff is most important. Converter is nice to have. "
    "I don't really care about the validator or stats module for now.",

    # Done
    "done",
]


async def simulate_scenario(
    scenario_num: int,
    responses: list[str],
    repo_path: Path,
) -> None:
    """Run the pipeline with pre-scripted responses."""
    print(f"\n{'=' * 70}")
    print(f"  SCENARIO {scenario_num}")
    print(f"{'=' * 70}\n")

    response_iter = iter(responses)
    turn_num = 0

    def sim_get_input(prompt: str) -> str:
        nonlocal turn_num
        turn_num += 1
        try:
            response = next(response_iter)
            print(f"\n  [USER #{turn_num}]: {response}\n")
            return response
        except StopIteration:
            print(f"\n  [USER #{turn_num}]: done\n")
            return "done"

    def sim_on_message(msg: str) -> None:
        # Truncate very long agent messages for readability
        lines = msg.split("\n")
        if len(lines) > 20:
            for line in lines[:10]:
                print(f"  {line}")
            print(f"  ... ({len(lines) - 20} lines omitted) ...")
            for line in lines[-10:]:
                print(f"  {line}")
        else:
            for line in lines:
                print(f"  {line}")

    rules = await run_elicitation(
        repo_path=repo_path,
        on_message=sim_on_message,
        get_input=sim_get_input,
        max_conversation_turns=5,
        max_review_rounds=1,
    )

    # Save results
    output_file = repo_path / f"simulation_scenario_{scenario_num}_rules.json"
    rules_data = {"rules": [r.model_dump() for r in rules]}
    with open(output_file, "w") as f:
        json.dump(rules_data, f, indent=2)

    print(f"\n{'=' * 70}")
    print(f"  SCENARIO {scenario_num} RESULTS")
    print(f"{'=' * 70}")
    print(f"  Generated {len(rules)} rules:")
    for r in rules:
        u = f"uncertainty={r.uncertainty}"
        print(f"    [{r.id}] {r.description[:70]}... ({u})")
    print(f"  Saved to: {output_file}")
    print(f"{'=' * 70}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Simulate rule elicitation conversations"
    )
    parser.add_argument(
        "--scenario",
        type=int,
        choices=[1, 2],
        default=None,
        help="Run a specific scenario (default: both)",
    )
    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="Path to repo (default: sample calculator project)",
    )
    args = parser.parse_args()

    # Default to sample calculator project
    if args.repo:
        repo_path = Path(args.repo).resolve()
    else:
        # Navigate from src/kekule/oracle/elicitor/simulate.py
        # up to kekule root, then into oracle/generator/samples/calculator
        kekule_root = Path(__file__).parent.parent.parent.parent.parent
        repo_path = (
            kekule_root / "oracle" / "generator" / "samples" / "calculator"
        ).resolve()

    if not repo_path.exists():
        print(f"Repository not found: {repo_path}")
        sys.exit(1)

    print(f"Using repository: {repo_path}")

    async def run():
        scenarios = {
            1: ("Clear intent", SCENARIO_1_RESPONSES),
            2: ("Vague intent", SCENARIO_2_RESPONSES),
        }

        if args.scenario:
            name, responses = scenarios[args.scenario]
            await simulate_scenario(args.scenario, responses, repo_path)
        else:
            for num, (name, responses) in scenarios.items():
                await simulate_scenario(num, responses, repo_path)

    asyncio.run(run())


if __name__ == "__main__":
    main()
