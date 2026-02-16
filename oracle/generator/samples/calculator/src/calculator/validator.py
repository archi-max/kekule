"""Input validation utilities."""

from __future__ import annotations

import re


class InputValidator:
    """Validate and parse user input for calculator operations."""

    OPERATORS = {"+", "-", "*", "/", "^", "%"}

    @staticmethod
    def is_numeric(value: str) -> bool:
        """Check if a string represents a valid number."""
        try:
            float(value)
            return True
        except (ValueError, TypeError):
            return False

    @staticmethod
    def parse_number(value: str) -> float:
        """Parse a string into a float.

        Supports:
        - Regular numbers: "42", "3.14", "-7"
        - Scientific notation: "1e5", "2.5e-3"

        Raises:
            ValueError: If the string is not a valid number.
        """
        value = value.strip()
        if not value:
            raise ValueError("Empty string is not a valid number")
        try:
            return float(value)
        except ValueError:
            raise ValueError(f"Cannot parse '{value}' as a number")

    @classmethod
    def validate_expression(cls, expression: str) -> bool:
        """Validate a simple binary expression like '3 + 4'.

        Only supports: number operator number

        Returns:
            True if the expression is valid.

        Raises:
            ValueError: With a description of what's wrong.
        """
        expression = expression.strip()
        if not expression:
            raise ValueError("Expression cannot be empty")

        # Match: optional-sign number, whitespace, operator, whitespace, optional-sign number
        pattern = r"^(-?\d+\.?\d*(?:[eE][+-]?\d+)?)\s*([+\-*/^%])\s*(-?\d+\.?\d*(?:[eE][+-]?\d+)?)$"
        match = re.match(pattern, expression)

        if not match:
            raise ValueError(
                f"Invalid expression: '{expression}'. "
                f"Expected format: 'number operator number' (e.g., '3 + 4')"
            )

        return True

    @classmethod
    def parse_expression(cls, expression: str) -> tuple[float, str, float]:
        """Parse a simple binary expression into (left, operator, right).

        Args:
            expression: A string like "3 + 4" or "10.5 * 2".

        Returns:
            Tuple of (left_operand, operator, right_operand).

        Raises:
            ValueError: If the expression is invalid.
        """
        cls.validate_expression(expression)

        pattern = r"^(-?\d+\.?\d*(?:[eE][+-]?\d+)?)\s*([+\-*/^%])\s*(-?\d+\.?\d*(?:[eE][+-]?\d+)?)$"
        match = re.match(pattern, expression.strip())
        assert match is not None  # validate_expression already checked

        left = float(match.group(1))
        operator = match.group(2)
        right = float(match.group(3))

        return (left, operator, right)
