"""
Phase 3: Reviewer Agent -- audits rules for measurability gaps.

Uses stateless query() to adversarially review each rule and determine
if it's concrete enough to generate a pytest from. Flags gaps as
either auto-resolvable (from code context) or needing user input.
"""

import json
import logging
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

from ..schemas import Rule
from .schemas import ReviewQuestion, ReviewResult

logger = logging.getLogger(__name__)


REVIEWER_SYSTEM_PROMPT = """
You are a Rule Reviewer for the Kekule Oracle verification system.

## Your Role
You are an ADVERSARIAL reviewer. Your job is to find gaps in verification rules
that would prevent a separate agent from writing a good pytest test.

## For Each Rule, Ask Yourself:
1. Could I write a pytest from ONLY this description and oracle_config?
2. Are the expected values/behaviors specific enough?
3. Are edge cases covered?
4. Is the scope clear (exactly which module/function/behavior)?
5. Are there conflicting rules?

## What to Flag
- **missing_threshold**: Rule says "should be fast" but no specific threshold
- **ambiguous_scope**: Rule says "handle errors" but doesn't say which errors or where
- **no_boundary**: Rule tests the happy path but ignores edge cases (empty input, overflow, negative values)
- **conflicting**: Two rules contradict each other
- **missing_expected**: Rule describes behavior but doesn't specify expected output

## Auto-Resolvable vs. Needs User
- **auto_resolvable=true**: The answer is IN THE CODE. Examples:
  - "What exception does this function raise?" -> read the source
  - "What are the valid input types?" -> read the type hints
  - "What does this function return for input X?" -> read the logic
- **auto_resolvable=false**: The answer is a PRODUCT DECISION. Examples:
  - "What latency is acceptable?"
  - "Should invalid input return null or raise an exception?"
  - "Is backwards compatibility with v1 required?"

## Output Format
Output ONLY a JSON object (no markdown, no commentary):
{
  "approved_rules": [
    { full Rule object for rules that pass review }
  ],
  "questions": [
    {
      "rule_id": "the_rule_id",
      "question": "What specific thing is missing or ambiguous?",
      "category": "missing_threshold|ambiguous_scope|no_boundary|conflicting|missing_expected",
      "auto_resolvable": true/false,
      "suggested_resolution": "If auto_resolvable, what should the rule say instead"
    }
  ],
  "auto_resolved": []
}

If ALL rules pass review, output:
{
  "approved_rules": [ all rules ],
  "questions": [],
  "auto_resolved": []
}
"""


async def review_rules(
    rules: list[Rule],
    repo_path: Path,
    model: str = "claude-sonnet-4-5",
    max_turns: int = 15,
) -> ReviewResult:
    """Review rules for measurability gaps.

    The reviewer agent reads each rule and the relevant code,
    then determines if the rule is concrete enough to test.

    Args:
        rules: Rules to review.
        repo_path: Path to the repository.
        model: Claude model to use.
        max_turns: Max agent turns.

    Returns:
        ReviewResult with approved rules and questions about gaps.
    """
    repo_path = Path(repo_path).resolve()

    rules_json = json.dumps([r.model_dump() for r in rules], indent=2)

    prompt = f"""## Rules to Review

{rules_json}

---

Review each rule. For each one, determine if a separate agent could write a
complete, correct pytest test from ONLY the rule's description and oracle_config.

Explore the codebase to verify that the target modules, classes, and methods
actually exist and behave as the rule claims.

Output your review as a JSON object with approved_rules, questions, and auto_resolved.
"""

    options = ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": REVIEWER_SYSTEM_PROMPT,
        },
        model=model,
        permission_mode="bypassPermissions",
        cwd=str(repo_path),
        allowed_tools=["Read", "Glob", "Grep", "Bash"],
        setting_sources=["user"],
        max_turns=max_turns,
    )

    last_text = ""
    logger.info(f"Phase 3: Reviewing {len(rules)} rules...")

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    last_text = block.text
        elif isinstance(message, ResultMessage):
            logger.info(
                f"Review completed: turns={message.num_turns}, "
                f"cost=${message.total_cost_usd or 0:.4f}"
            )

    # Parse the review result
    from . import _parse_json_from_text

    result = _parse_json_from_text(last_text)
    if result is None:
        logger.warning("Could not parse review result, approving all rules")
        return ReviewResult(approved_rules=rules)

    # Build ReviewResult, handling partial parses
    try:
        approved = [
            Rule(**r) for r in result.get("approved_rules", [])
        ]
        questions = [
            ReviewQuestion(**q) for q in result.get("questions", [])
        ]
        auto_resolved = result.get("auto_resolved", [])

        return ReviewResult(
            approved_rules=approved,
            questions=questions,
            auto_resolved=auto_resolved,
        )
    except Exception as e:
        logger.warning(f"Error parsing review result: {e}, approving all rules")
        return ReviewResult(approved_rules=rules)
