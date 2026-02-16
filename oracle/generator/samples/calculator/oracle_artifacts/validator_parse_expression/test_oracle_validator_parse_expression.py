"""Oracle test for rule: validator_parse_expression

This test verifies that InputValidator.parse_expression correctly:
- Parses simple binary expressions like '3 + 4' into (3.0, '+', 4.0)
- Handles all operators (+, -, *, /, ^, %)
- Raises ValueError for invalid expressions (empty, incomplete, malformed, or multi-operator)

Rule: InputValidator.parse_expression should correctly parse simple binary expressions
like '3 + 4' into (3.0, '+', 4.0). It should handle all operators (+, -, *, /, ^, %)
and raise ValueError for invalid expressions.
"""

import sys
from pathlib import Path

import pytest

# Add src directory to path for imports
repo_root = Path(__file__).parent.parent.parent
src_path = repo_root / "src"
sys.path.insert(0, str(src_path))

from calculator.validator import InputValidator


class TestInputValidatorParseExpression:
    """Test suite for InputValidator.parse_expression functionality."""

    def test_parse_addition_expression(self):
        """Test that parse_expression correctly parses '3 + 4' into (3.0, '+', 4.0)."""
        result = InputValidator.parse_expression("3 + 4")
        expected = (3.0, "+", 4.0)
        assert result == expected, (
            f"Expected parse_expression('3 + 4') to return {expected}, but got {result}"
        )

    def test_parse_multiplication_expression(self):
        """Test that parse_expression correctly parses '10 * 2' into (10.0, '*', 2.0)."""
        result = InputValidator.parse_expression("10 * 2")
        expected = (10.0, "*", 2.0)
        assert result == expected, (
            f"Expected parse_expression('10 * 2') to return {expected}, but got {result}"
        )

    def test_parse_division_expression(self):
        """Test that parse_expression correctly parses '7 / 3' into (7.0, '/', 3.0)."""
        result = InputValidator.parse_expression("7 / 3")
        expected = (7.0, "/", 3.0)
        assert result == expected, (
            f"Expected parse_expression('7 / 3') to return {expected}, but got {result}"
        )

    def test_parse_negative_operand_expression(self):
        """Test that parse_expression correctly parses '-5 + 3' into (-5.0, '+', 3.0)."""
        result = InputValidator.parse_expression("-5 + 3")
        expected = (-5.0, "+", 3.0)
        assert result == expected, (
            f"Expected parse_expression('-5 + 3') to return {expected}, but got {result}"
        )

    def test_parse_subtraction_expression(self):
        """Test that parse_expression handles subtraction operator."""
        result = InputValidator.parse_expression("8 - 5")
        expected = (8.0, "-", 5.0)
        assert result == expected, (
            f"Expected parse_expression('8 - 5') to return {expected}, but got {result}"
        )

    def test_parse_power_expression(self):
        """Test that parse_expression handles power operator (^)."""
        result = InputValidator.parse_expression("2 ^ 3")
        expected = (2.0, "^", 3.0)
        assert result == expected, (
            f"Expected parse_expression('2 ^ 3') to return {expected}, but got {result}"
        )

    def test_parse_modulo_expression(self):
        """Test that parse_expression handles modulo operator (%)."""
        result = InputValidator.parse_expression("10 % 3")
        expected = (10.0, "%", 3.0)
        assert result == expected, (
            f"Expected parse_expression('10 % 3') to return {expected}, but got {result}"
        )

    def test_parse_expression_with_decimals(self):
        """Test that parse_expression handles decimal numbers."""
        result = InputValidator.parse_expression("3.5 + 2.1")
        expected = (3.5, "+", 2.1)
        assert result == expected, (
            f"Expected parse_expression('3.5 + 2.1') to return {expected}, but got {result}"
        )

    def test_parse_expression_without_spaces(self):
        """Test that parse_expression handles expressions without spaces."""
        result = InputValidator.parse_expression("5+3")
        expected = (5.0, "+", 3.0)
        assert result == expected, (
            f"Expected parse_expression('5+3') to return {expected}, but got {result}"
        )

    def test_parse_expression_with_extra_spaces(self):
        """Test that parse_expression handles expressions with extra spaces."""
        result = InputValidator.parse_expression("  5   +   3  ")
        expected = (5.0, "+", 3.0)
        assert result == expected, (
            f"Expected parse_expression('  5   +   3  ') to return {expected}, but got {result}"
        )

    def test_empty_expression_raises_valueerror(self):
        """Test that parse_expression raises ValueError for empty string."""
        with pytest.raises(ValueError) as exc_info:
            InputValidator.parse_expression("")

        assert "empty" in str(exc_info.value).lower(), (
            f"Expected ValueError message to mention 'empty', but got: {exc_info.value}"
        )

    def test_text_only_raises_valueerror(self):
        """Test that parse_expression raises ValueError for non-numeric text like 'hello'."""
        with pytest.raises(ValueError) as exc_info:
            InputValidator.parse_expression("hello")

        assert "invalid" in str(exc_info.value).lower(), (
            f"Expected ValueError message to mention 'invalid', but got: {exc_info.value}"
        )

    def test_incomplete_expression_missing_right_operand_raises_valueerror(self):
        """Test that parse_expression raises ValueError for '3 +' (missing right operand)."""
        with pytest.raises(ValueError) as exc_info:
            InputValidator.parse_expression("3 +")

        assert "invalid" in str(exc_info.value).lower(), (
            f"Expected ValueError message to mention 'invalid', but got: {exc_info.value}"
        )

    def test_incomplete_expression_missing_left_operand_raises_valueerror(self):
        """Test that parse_expression raises ValueError for '+ 4' (missing left operand)."""
        with pytest.raises(ValueError) as exc_info:
            InputValidator.parse_expression("+ 4")

        assert "invalid" in str(exc_info.value).lower(), (
            f"Expected ValueError message to mention 'invalid', but got: {exc_info.value}"
        )

    def test_multiple_operators_raises_valueerror(self):
        """Test that parse_expression raises ValueError for '3 + 4 + 5' (multiple operators)."""
        with pytest.raises(ValueError) as exc_info:
            InputValidator.parse_expression("3 + 4 + 5")

        assert "invalid" in str(exc_info.value).lower(), (
            f"Expected ValueError message to mention 'invalid', but got: {exc_info.value}"
        )


def test_all_valid_expressions_from_oracle_config():
    """Test all valid expression test cases from the oracle configuration."""
    test_cases = [
        {"input": "3 + 4", "expected": (3.0, "+", 4.0)},
        {"input": "10 * 2", "expected": (10.0, "*", 2.0)},
        {"input": "7 / 3", "expected": (7.0, "/", 3.0)},
        {"input": "-5 + 3", "expected": (-5.0, "+", 3.0)},
    ]

    for case in test_cases:
        input_expr = case["input"]
        expected = case["expected"]

        result = InputValidator.parse_expression(input_expr)
        assert result == expected, (
            f"Failed for expression '{input_expr}': "
            f"expected {expected}, but got {result}"
        )


def test_all_invalid_expressions_from_oracle_config():
    """Test all invalid expression test cases from the oracle configuration."""
    invalid_expressions = [
        "",
        "hello",
        "3 +",
        "+ 4",
        "3 + 4 + 5",
    ]

    for expr in invalid_expressions:
        with pytest.raises(ValueError, match=".*") as exc_info:
            InputValidator.parse_expression(expr)

        # Verify that a ValueError was raised with some message
        assert str(exc_info.value), (
            f"Expected ValueError with a message for expression '{expr}', "
            f"but got empty message"
        )
