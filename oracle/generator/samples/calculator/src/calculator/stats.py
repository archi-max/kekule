"""Statistical functions."""

from __future__ import annotations

import math


class Statistics:
    """Compute basic statistics on numeric data."""

    @staticmethod
    def mean(data: list[float]) -> float:
        """Calculate the arithmetic mean.

        Raises:
            ValueError: If data is empty.
        """
        if not data:
            raise ValueError("Cannot compute mean of empty dataset")
        return sum(data) / len(data)

    @staticmethod
    def median(data: list[float]) -> float:
        """Calculate the median.

        Raises:
            ValueError: If data is empty.
        """
        if not data:
            raise ValueError("Cannot compute median of empty dataset")
        sorted_data = sorted(data)
        n = len(sorted_data)
        mid = n // 2
        if n % 2 == 0:
            return (sorted_data[mid - 1] + sorted_data[mid]) / 2
        return sorted_data[mid]

    @staticmethod
    def variance(data: list[float]) -> float:
        """Calculate the population variance.

        Raises:
            ValueError: If data is empty.
        """
        if not data:
            raise ValueError("Cannot compute variance of empty dataset")
        avg = sum(data) / len(data)
        return sum((x - avg) ** 2 for x in data) / len(data)

    @staticmethod
    def std_dev(data: list[float]) -> float:
        """Calculate the population standard deviation.

        Raises:
            ValueError: If data is empty.
        """
        return math.sqrt(Statistics.variance(data))

    @staticmethod
    def min_max(data: list[float]) -> tuple[float, float]:
        """Return (min, max) of the data.

        Raises:
            ValueError: If data is empty.
        """
        if not data:
            raise ValueError("Cannot compute min/max of empty dataset")
        return (min(data), max(data))

    @staticmethod
    def percentile(data: list[float], p: float) -> float:
        """Calculate the p-th percentile using linear interpolation.

        Args:
            data: List of numeric values.
            p: Percentile to compute (0-100).

        Raises:
            ValueError: If data is empty or p is out of range.
        """
        if not data:
            raise ValueError("Cannot compute percentile of empty dataset")
        if not 0 <= p <= 100:
            raise ValueError(f"Percentile must be between 0 and 100, got {p}")

        sorted_data = sorted(data)
        n = len(sorted_data)

        if n == 1:
            return sorted_data[0]

        # Linear interpolation
        rank = (p / 100) * (n - 1)
        lower = int(math.floor(rank))
        upper = int(math.ceil(rank))
        fraction = rank - lower

        if lower == upper:
            return sorted_data[lower]
        return sorted_data[lower] + fraction * (sorted_data[upper] - sorted_data[lower])
