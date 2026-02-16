"""Oracle test for rule: calc_add_basic

This test verifies that Calculator.add correctly handles:
- Addition of two positive numbers
- Addition of two negative numbers
- Addition of a positive and negative number (mixed)
- Addition with zero

Rule: Calculator.add should correctly add two positive numbers, two negative numbers,
and a mix of positive and negative. It should also handle zero.
"""

import sys
from pathlib import Path

import pytest

# Add src directory to path for imports
repo_root = Path(__file__).parent.parent.parent
src_path = repo_root / "src"
sys.path.insert(0, str(src_path))

from calculator.core import Calculator


class TestCalculatorAddBasic:
    """Test suite for Calculator.add basic functionality."""

    def test_add_two_positive_numbers(self):
        """Test that add correctly adds two positive numbers (2 + 3 = 5)."""
        calc = Calculator()
        result = calc.add(2, 3)
        assert result == 5, f"Expected 2 + 3 = 5, but got {result}"

    def test_add_two_negative_numbers(self):
        """Test that add correctly adds two negative numbers (-1 + -1 = -2)."""
        calc = Calculator()
        result = calc.add(-1, -1)
        assert result == -2, f"Expected -1 + -1 = -2, but got {result}"

    def test_add_mixed_positive_and_negative(self):
        """Test that add correctly adds a negative and positive number (-5 + 5 = 0)."""
        calc = Calculator()
        result = calc.add(-5, 5)
        assert result == 0, f"Expected -5 + 5 = 0, but got {result}"

    def test_add_zeros(self):
        """Test that add correctly handles zero (0 + 0 = 0)."""
        calc = Calculator()
        result = calc.add(0, 0)
        assert result == 0, f"Expected 0 + 0 = 0, but got {result}"


def test_all_oracle_test_cases():
    """Test all test cases from the oracle configuration in a single test."""
    test_cases = [
        {"a": 2, "b": 3, "expected": 5, "description": "two positive numbers"},
        {"a": -1, "b": -1, "expected": -2, "description": "two negative numbers"},
        {"a": -5, "b": 5, "expected": 0, "description": "mixed positive and negative"},
        {"a": 0, "b": 0, "expected": 0, "description": "zeros"},
    ]

    calc = Calculator()
    for case in test_cases:
        a = case["a"]
        b = case["b"]
        expected = case["expected"]
        description = case["description"]

        result = calc.add(a, b)
        assert result == expected, (
            f"Failed for {description}: "
            f"add({a}, {b}) expected {expected}, but got {result}"
        )
