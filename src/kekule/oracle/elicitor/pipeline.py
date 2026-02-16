"""
Pipeline orchestrator -- runs the 3-phase rule elicitation loop.

Phase 1: Conversation Agent captures user intent (multi-turn)
Phase 2: Rule Generator produces structured Rules from intent
Phase 3: Reviewer audits rules, auto-resolves or escalates gaps
Repeat Phase 2-3 until all rules pass review or max rounds reached.
"""

import json
import logging
from pathlib import Path
from typing import Callable

from ..schemas import Rule
from .conversation import capture_intent
from .escalation import format_escalation_questions, triage_questions
from .reviewer import review_rules
from .rule_generator import generate_rules, refine_rules
from .schemas import Intent

logger = logging.getLogger(__name__)


async def run_elicitation(
    repo_path: str | Path,
    on_message: Callable[[str], None] | None = None,
    get_input: Callable[[str], str] | None = None,
    model: str = "claude-sonnet-4-5",
    max_conversation_turns: int = 10,
    max_review_rounds: int = 2,
) -> list[Rule]:
    """Run the full 3-phase rule elicitation pipeline.

    Phase 1: Multi-turn conversation to capture intent
    Phase 2: Generate structured rules from intent
    Phase 3: Review rules, auto-resolve gaps, escalate to user if needed
    Repeat 2-3 until rules pass review.

    Args:
        repo_path: Path to the repository.
        on_message: Callback to display messages to user. Defaults to print.
        get_input: Callback to get user input. Defaults to stdin.
        model: Claude model for all agents.
        max_conversation_turns: Max back-and-forth in Phase 1.
        max_review_rounds: Max review/refine cycles.

    Returns:
        List of confirmed Rule objects.
    """
    repo_path = Path(repo_path).resolve()

    if on_message is None:
        on_message = print
    if get_input is None:
        get_input = lambda prompt: input(f"\n{prompt}\n> ")

    # ── Phase 1: Conversation ──────────────────────────────────
    on_message("\n=== Phase 1: Understanding Your Requirements ===\n")

    intent = await capture_intent(
        repo_path=repo_path,
        on_message=on_message,
        get_input=get_input,
        model=model,
        max_conversation_turns=max_conversation_turns,
    )

    on_message(f"\n--- Intent captured: {len(intent.requirements)} requirements ---")
    for req in intent.requirements:
        tag = "MEASURABLE" if req.measurable else "NEEDS DETAIL"
        on_message(f"  [{req.priority.value.upper()}] [{tag}] {req.description}")

    # ── Phase 2: Rule Generation ───────────────────────────────
    on_message("\n=== Phase 2: Generating Verification Rules ===\n")

    rules = await generate_rules(
        intent=intent,
        repo_path=repo_path,
        model=model,
    )

    on_message(f"\n--- Generated {len(rules)} rules ---")
    for rule in rules:
        on_message(f"  [{rule.id}] {rule.description[:80]}")

    # ── Phase 3: Review Loop ───────────────────────────────────
    for round_num in range(max_review_rounds):
        on_message(f"\n=== Phase 3: Review (round {round_num + 1}) ===\n")

        review = await review_rules(
            rules=rules,
            repo_path=repo_path,
            model=model,
        )

        if not review.questions:
            on_message("All rules passed review.")
            rules = review.approved_rules if review.approved_rules else rules
            break

        on_message(
            f"Reviewer found {len(review.questions)} gaps "
            f"({len(review.approved_rules)} rules approved)"
        )

        # Triage questions
        auto_questions, user_questions = triage_questions(review.questions)

        # Auto-resolve from code
        if auto_questions:
            on_message(
                f"\nAuto-resolving {len(auto_questions)} gaps from code context..."
            )
            for q in auto_questions:
                on_message(f"  [{q.rule_id}] {q.question}")
                if q.suggested_resolution:
                    on_message(f"    -> {q.suggested_resolution}")

            rules = await refine_rules(
                rules=rules,
                questions=auto_questions,
                repo_path=repo_path,
                model=model,
            )
            on_message(f"  Refined to {len(rules)} rules")

        # Escalate to user
        if user_questions:
            escalation_text = format_escalation_questions(user_questions)
            on_message(f"\n{escalation_text}")

            user_response = get_input("Your clarification")

            if user_response and user_response.strip().lower() != "skip":
                # Feed user clarification back through refinement
                clarification_questions = [
                    type(q).model_validate({
                        **q.model_dump(),
                        "suggested_resolution": user_response,
                        "auto_resolvable": True,
                    })
                    for q in user_questions
                ]
                rules = await refine_rules(
                    rules=rules,
                    questions=clarification_questions,
                    repo_path=repo_path,
                    model=model,
                )
            else:
                on_message("Skipping user questions, accepting rules as-is.")
                # Merge approved + current rules (prefer approved versions)
                approved_ids = {r.id for r in review.approved_rules}
                rules = review.approved_rules + [
                    r for r in rules if r.id not in approved_ids
                ]
    else:
        on_message(f"\nMax review rounds ({max_review_rounds}) reached.")

    # Set all rules to confirmed status
    confirmed_rules = []
    for rule in rules:
        data = rule.model_dump()
        data["status"] = "confirmed"
        confirmed_rules.append(Rule(**data))

    on_message(f"\n=== Elicitation Complete: {len(confirmed_rules)} rules ===\n")
    for rule in confirmed_rules:
        on_message(f"  [{rule.id}] {rule.description[:80]}")

    return confirmed_rules
