"""
Phase 2: Rule Generator -- converts Intent into structured Rules.

Uses stateless query() to explore the codebase and produce concrete,
testable Rule objects grounded in actual code structure.
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
from .schemas import Intent, ReviewQuestion

logger = logging.getLogger(__name__)


RULE_GENERATOR_SYSTEM_PROMPT = """
You are a Rule Generator for the Kekule Oracle verification system.

## Your Mission
Given a structured Intent (user's verification requirements), explore the codebase
and produce concrete, testable Rules that a separate agent can turn into pytest tests.

## Workflow
1. Read the Intent carefully -- understand the summary, priorities, and each requirement.
2. For each requirement, explore the relevant code using Read, Glob, Grep, Bash.
3. Produce a Rule for each requirement (or multiple Rules if the requirement is broad).
4. Ground every Rule in actual code: name the real module, class, method.
5. Add concrete test cases in oracle_config when the code makes expected behavior clear.

## Rule Quality Requirements
- Every rule MUST reference a real module/class/method that exists in the codebase
- Every rule MUST have a description specific enough to write a pytest from
- Every rule SHOULD include oracle_config with target_module, class, method
- Every rule SHOULD include test_cases with concrete inputs/outputs when possible
- Uncertainty should be LOW (0.0-0.2) since the conversation already clarified intent
- Set status to "draft"

## Output Format
Output ONLY a JSON object (no markdown, no commentary):
{
  "rules": [
    {
      "id": "snake_case_id",
      "description": "Specific testable behavior",
      "oracle_type": "pytest",
      "oracle_config": {
        "target_module": "path/to/module.py",
        "class": "ClassName",
        "method": "method_name",
        "test_cases": [{"input": ..., "expected": ...}]
      },
      "uncertainty": 0.1,
      "status": "draft"
    }
  ]
}
"""

REFINE_PROMPT_TEMPLATE = """
Some rules need improvement based on reviewer feedback. Here are the current rules
and the issues found:

## Current Rules
{rules_json}

## Issues to Fix
{questions_json}

For each issue:
- If the reviewer provided a suggested_resolution, use it
- Otherwise, explore the code to find the answer
- Update the rule's description, oracle_config, or test_cases to address the gap

Output the COMPLETE updated rules list as JSON (same format as before).
Include ALL rules, not just the ones that changed.
"""


async def generate_rules(
    intent: Intent,
    repo_path: Path,
    model: str = "claude-sonnet-4-5",
    max_turns: int = 20,
) -> list[Rule]:
    """Generate concrete Rules from a structured Intent.

    Explores the codebase to ground each requirement in actual code,
    producing testable Rules with specific modules, methods, and test cases.

    Args:
        intent: Structured intent from the conversation phase.
        repo_path: Path to the repository.
        model: Claude model to use.
        max_turns: Max agent turns.

    Returns:
        List of Rule objects.
    """
    repo_path = Path(repo_path).resolve()

    prompt = _build_generation_prompt(intent)

    options = ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": RULE_GENERATOR_SYSTEM_PROMPT,
        },
        model=model,
        permission_mode="bypassPermissions",
        cwd=str(repo_path),
        allowed_tools=["Read", "Glob", "Grep", "Bash"],
        setting_sources=["user"],
        max_turns=max_turns,
    )

    last_text = ""
    logger.info("Phase 2: Generating rules from intent...")

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    last_text = block.text
        elif isinstance(message, ResultMessage):
            logger.info(
                f"Rule generation completed: turns={message.num_turns}, "
                f"cost=${message.total_cost_usd or 0:.4f}"
            )

    from . import _parse_rules_from_text

    rules = _parse_rules_from_text(last_text)
    logger.info(f"Generated {len(rules)} rules")
    return rules


async def refine_rules(
    rules: list[Rule],
    questions: list[ReviewQuestion],
    repo_path: Path,
    model: str = "claude-sonnet-4-5",
    max_turns: int = 15,
) -> list[Rule]:
    """Refine rules based on reviewer feedback.

    Takes the current rules and auto-resolvable questions,
    explores the code to fill in gaps, and returns updated rules.

    Args:
        rules: Current rules to refine.
        questions: Reviewer questions to address.
        repo_path: Path to the repository.
        model: Claude model to use.
        max_turns: Max agent turns.

    Returns:
        Updated list of Rule objects.
    """
    repo_path = Path(repo_path).resolve()

    rules_json = json.dumps(
        [r.model_dump() for r in rules], indent=2
    )
    questions_json = json.dumps(
        [q.model_dump() for q in questions], indent=2
    )
    prompt = REFINE_PROMPT_TEMPLATE.format(
        rules_json=rules_json,
        questions_json=questions_json,
    )

    options = ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": RULE_GENERATOR_SYSTEM_PROMPT,
        },
        model=model,
        permission_mode="bypassPermissions",
        cwd=str(repo_path),
        allowed_tools=["Read", "Glob", "Grep", "Bash"],
        setting_sources=["user"],
        max_turns=max_turns,
    )

    last_text = ""
    logger.info(f"Refining {len(rules)} rules based on {len(questions)} questions...")

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    last_text = block.text
        elif isinstance(message, ResultMessage):
            logger.info(
                f"Rule refinement completed: turns={message.num_turns}, "
                f"cost=${message.total_cost_usd or 0:.4f}"
            )

    from . import _parse_rules_from_text

    refined = _parse_rules_from_text(last_text)
    if refined:
        logger.info(f"Refined to {len(refined)} rules")
        return refined

    logger.warning("Refinement produced no parseable rules, keeping originals")
    return rules


def _build_generation_prompt(intent: Intent) -> str:
    """Build the prompt for the rule generator from structured intent."""
    requirements_text = ""
    for i, req in enumerate(intent.requirements, 1):
        measurable_tag = " [MEASURABLE]" if req.measurable else " [NEEDS CONCRETENESS]"
        requirements_text += (
            f"{i}. [{req.priority.value.upper()}] {req.description}"
            f" (area: {req.area}){measurable_tag}\n"
        )

    priorities_text = "\n".join(
        f"  {i}. {p}" for i, p in enumerate(intent.priorities, 1)
    )

    return f"""## User's Verification Intent

### Summary
{intent.summary}

### Priorities (in order)
{priorities_text}

### Requirements
{requirements_text}

### Additional Context
{intent.context}

---

Explore the repository and generate concrete, testable Rules for each requirement.
Output the rules as a JSON object with a "rules" array.
"""
