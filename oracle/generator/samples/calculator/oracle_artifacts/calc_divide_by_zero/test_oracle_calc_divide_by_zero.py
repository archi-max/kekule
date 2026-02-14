"""Oracle test for rule: calc_divide_by_zero

This test verifies that Calculator.divide correctly handles:
- Raising ZeroDivisionError when the divisor (b) is zero
- Normal division operation for non-zero divisors
- Various edge cases including positive, negative, and mixed values

Rule: Calculator.divide must raise ZeroDivisionError when the divisor is zero.
It should work normally for non-zero divisors.
"""

import sys
from pathlib import Path

import pytest

# Add src directory to path for imports
repo_root = Path(__file__).parent.parent.parent
src_path = repo_root / "src"
sys.path.insert(0, str(src_path))

from calculator.core import Calculator


class TestCalculatorDivideByZero:
    """Test suite for Calculator.divide zero division error handling."""

    def test_divide_by_zero_raises_exception(self):
        """Test that divide raises ZeroDivisionError when divisor is zero."""
        calc = Calculator()
        with pytest.raises(ZeroDivisionError) as exc_info:
            calc.divide(10, 0)

        assert "Cannot divide by zero" in str(exc_info.value), (
            f"Expected ZeroDivisionError with message containing 'Cannot divide by zero', "
            f"but got: {exc_info.value}"
        )

    def test_divide_negative_by_zero_raises_exception(self):
        """Test that divide raises ZeroDivisionError even with negative dividend."""
        calc = Calculator()
        with pytest.raises(ZeroDivisionError):
            calc.divide(-5, 0)

    def test_divide_zero_by_zero_raises_exception(self):
        """Test that divide raises ZeroDivisionError for 0/0."""
        calc = Calculator()
        with pytest.raises(ZeroDivisionError):
            calc.divide(0, 0)

    def test_divide_normal_case_positive_numbers(self):
        """Test that divide works correctly for positive numbers (10 / 2 = 5.0)."""
        calc = Calculator()
        result = calc.divide(10, 2)
        assert result == 5.0, f"Expected 10 / 2 = 5.0, but got {result}"

    def test_divide_normal_case_negative_dividend(self):
        """Test that divide works correctly for negative dividend (-9 / 3 = -3.0)."""
        calc = Calculator()
        result = calc.divide(-9, 3)
        assert result == -3.0, f"Expected -9 / 3 = -3.0, but got {result}"

    def test_divide_normal_case_negative_divisor(self):
        """Test that divide works correctly for negative divisor (10 / -2 = -5.0)."""
        calc = Calculator()
        result = calc.divide(10, -2)
        assert result == -5.0, f"Expected 10 / -2 = -5.0, but got {result}"

    def test_divide_normal_case_both_negative(self):
        """Test that divide works correctly for both negative numbers (-10 / -2 = 5.0)."""
        calc = Calculator()
        result = calc.divide(-10, -2)
        assert result == 5.0, f"Expected -10 / -2 = 5.0, but got {result}"

    def test_divide_zero_by_nonzero(self):
        """Test that divide works correctly for zero dividend (0 / 5 = 0.0)."""
        calc = Calculator()
        result = calc.divide(0, 5)
        assert result == 0.0, f"Expected 0 / 5 = 0.0, but got {result}"


def test_all_oracle_test_cases():
    """Test all test cases from the oracle configuration in a single test."""
    # Normal cases from oracle_config
    normal_cases = [
        {"a": 10, "b": 2, "expected": 5.0, "description": "positive numbers (10 / 2)"},
        {"a": -9, "b": 3, "expected": -3.0, "description": "negative dividend (-9 / 3)"},
    ]

    calc = Calculator()

    # Test normal cases
    for case in normal_cases:
        a = case["a"]
        b = case["b"]
        expected = case["expected"]
        description = case["description"]

        result = calc.divide(a, b)
        assert result == expected, (
            f"Failed for {description}: "
            f"divide({a}, {b}) expected {expected}, but got {result}"
        )

    # Test zero division cases
    zero_division_cases = [
        {"a": 10, "b": 0, "description": "positive dividend by zero"},
        {"a": -5, "b": 0, "description": "negative dividend by zero"},
        {"a": 0, "b": 0, "description": "zero by zero"},
    ]

    for case in zero_division_cases:
        a = case["a"]
        b = case["b"]
        description = case["description"]

        with pytest.raises(ZeroDivisionError) as exc_info:
            calc.divide(a, b)

        assert "Cannot divide by zero" in str(exc_info.value), (
            f"Failed for {description}: "
            f"divide({a}, {b}) should raise ZeroDivisionError with proper message, "
            f"but got: {exc_info.value}"
        )
