"""
Escalation logic -- triages reviewer questions into auto-resolvable vs. needs-user.

Pure logic layer, no LLM calls. The auto_resolve function delegates
back to the rule generator for code-based resolution.
"""

import logging

from ..schemas import Rule
from .schemas import ReviewQuestion

logger = logging.getLogger(__name__)


def triage_questions(
    questions: list[ReviewQuestion],
) -> tuple[list[ReviewQuestion], list[ReviewQuestion]]:
    """Split reviewer questions into auto-resolvable and needs-user.

    Args:
        questions: All questions from the reviewer.

    Returns:
        Tuple of (auto_resolvable, needs_user) question lists.
    """
    auto = [q for q in questions if q.auto_resolvable]
    needs_user = [q for q in questions if not q.auto_resolvable]

    logger.info(
        f"Triage: {len(auto)} auto-resolvable, {len(needs_user)} need user input"
    )
    return auto, needs_user


def format_escalation_questions(questions: list[ReviewQuestion]) -> str:
    """Format escalated questions for display to the user.

    Args:
        questions: Questions that need user input.

    Returns:
        Formatted string for display.
    """
    if not questions:
        return ""

    lines = ["The reviewer found some gaps that need your input:\n"]
    for i, q in enumerate(questions, 1):
        lines.append(f"  {i}. [{q.rule_id}] {q.question}")
        lines.append(f"     Category: {q.category}")
        if q.suggested_resolution:
            lines.append(f"     Suggestion: {q.suggested_resolution}")
        lines.append("")

    lines.append(
        "Please provide clarification for these questions "
        "(or 'skip' to accept the rules as-is):"
    )
    return "\n".join(lines)
