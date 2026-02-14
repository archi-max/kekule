"""Oracle test for rule: stats_mean_basic

This test verifies that Statistics.mean correctly:
- Calculates the arithmetic mean for a list of numbers
- Returns the correct mean for various test cases (multiple values, single value, negative values)
- Raises ValueError for an empty list

Rule: Statistics.mean should return the correct arithmetic mean for a list of numbers.
It should raise ValueError for an empty list.
"""

import sys
from pathlib import Path

import pytest

# Add src directory to path for imports
repo_root = Path(__file__).parent.parent.parent
src_path = repo_root / "src"
sys.path.insert(0, str(src_path))

from calculator.stats import Statistics


class TestStatisticsMeanBasic:
    """Test suite for Statistics.mean basic functionality."""

    def test_mean_multiple_values(self):
        """Test that mean correctly calculates the arithmetic mean of [1, 2, 3, 4, 5]."""
        result = Statistics.mean([1, 2, 3, 4, 5])
        expected = 3.0
        assert result == expected, f"Expected mean([1, 2, 3, 4, 5]) = {expected}, but got {result}"

    def test_mean_single_value(self):
        """Test that mean correctly handles a single value [10]."""
        result = Statistics.mean([10])
        expected = 10.0
        assert result == expected, f"Expected mean([10]) = {expected}, but got {result}"

    def test_mean_negative_and_positive(self):
        """Test that mean correctly calculates the mean of [-1, 1]."""
        result = Statistics.mean([-1, 1])
        expected = 0.0
        assert result == expected, f"Expected mean([-1, 1]) = {expected}, but got {result}"

    def test_mean_empty_list_raises_value_error(self):
        """Test that mean raises ValueError for an empty list."""
        with pytest.raises(ValueError, match="Cannot compute mean of empty dataset"):
            Statistics.mean([])


def test_all_oracle_test_cases():
    """Test all test cases from the oracle configuration in a single test."""
    test_cases = [
        {"data": [1, 2, 3, 4, 5], "expected": 3.0, "description": "multiple values"},
        {"data": [10], "expected": 10.0, "description": "single value"},
        {"data": [-1, 1], "expected": 0.0, "description": "negative and positive values"},
    ]

    for case in test_cases:
        data = case["data"]
        expected = case["expected"]
        description = case["description"]

        result = Statistics.mean(data)
        assert result == expected, (
            f"Failed for {description}: "
            f"mean({data}) expected {expected}, but got {result}"
        )


def test_mean_empty_list_error():
    """Test that mean raises ValueError for an empty list (edge case verification)."""
    with pytest.raises(ValueError, match="Cannot compute mean of empty dataset"):
        Statistics.mean([])
