"""
Input/Output schemas for the Expert Solver Agent.

These are flexible schemas that can evolve as the API develops.
"""

from dataclasses import dataclass, field
from typing import Any
from datetime import datetime
import json


@dataclass
class PreviousAttempt:
    """A previous attempt by another agent to solve the question."""

    agent_id: str
    timestamp: str
    content: str
    outcome: str  # "partial", "failed", "inconclusive"
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PreviousAttempt":
        return cls(
            agent_id=data.get("agent_id", "unknown"),
            timestamp=data.get("timestamp", ""),
            content=data.get("content", ""),
            outcome=data.get("outcome", "inconclusive"),
            notes=data.get("notes", "")
        )


@dataclass
class Question:
    """A question to be solved."""

    question_id: str
    title: str
    body: str
    tags: list[str] = field(default_factory=list)
    context: str = ""  # Additional context like error logs, environment info
    repo_url: str = ""  # Optional: repository URL if applicable
    previous_attempts: list[PreviousAttempt] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Question":
        attempts = [
            PreviousAttempt.from_dict(a)
            for a in data.get("previous_attempts", [])
        ]
        return cls(
            question_id=data.get("question_id", data.get("id", "unknown")),
            title=data.get("title", "Untitled"),
            body=data.get("body", data.get("content", "")),
            tags=data.get("tags", []),
            context=data.get("context", ""),
            repo_url=data.get("repo_url", ""),
            previous_attempts=attempts,
            metadata=data.get("metadata", {})
        )

    @classmethod
    def from_json_file(cls, path: str) -> "Question":
        with open(path, "r") as f:
            data = json.load(f)
        return cls.from_dict(data)

    @classmethod
    def from_text_file(cls, path: str) -> "Question":
        """Parse a simple text file format."""
        with open(path, "r") as f:
            content = f.read()

        # Simple parsing: first line is title, rest is body
        lines = content.strip().split("\n")
        title = lines[0] if lines else "Untitled"
        body = "\n".join(lines[1:]) if len(lines) > 1 else ""

        return cls(
            question_id=path,
            title=title,
            body=body
        )


@dataclass
class SolverResponse:
    """The agent's response to a question."""

    question_id: str
    response_type: str  # "attempt" or "answer"
    content: str
    confidence: float  # 0.0 to 1.0
    reasoning: str
    steps_taken: list[str] = field(default_factory=list)
    code_snippets: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_text(self) -> str:
        """Convert to unstructured text output."""
        lines = [
            f"# Expert Solver Response",
            f"",
            f"**Question ID**: {self.question_id}",
            f"**Response Type**: {self.response_type.upper()}",
            f"**Confidence**: {self.confidence:.0%}",
            f"**Timestamp**: {self.timestamp}",
            f"",
            f"---",
            f"",
            f"## Reasoning",
            f"",
            self.reasoning,
            f"",
            f"---",
            f"",
            f"## Solution",
            f"",
            self.content,
            f"",
        ]

        if self.steps_taken:
            lines.extend([
                f"---",
                f"",
                f"## Steps Taken",
                f"",
            ])
            for i, step in enumerate(self.steps_taken, 1):
                lines.append(f"{i}. {step}")
            lines.append("")

        if self.code_snippets:
            lines.extend([
                f"---",
                f"",
                f"## Code Snippets",
                f"",
            ])
            for snippet in self.code_snippets:
                lines.append(f"```")
                lines.append(snippet)
                lines.append(f"```")
                lines.append("")

        if self.references:
            lines.extend([
                f"---",
                f"",
                f"## References",
                f"",
            ])
            for ref in self.references:
                lines.append(f"- {ref}")
            lines.append("")

        return "\n".join(lines)

    def save(self, path: str) -> None:
        """Save response to a text file."""
        with open(path, "w") as f:
            f.write(self.to_text())
