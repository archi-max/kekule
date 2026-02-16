"""Unit conversion utilities."""

from __future__ import annotations


class TemperatureConverter:
    """Convert between temperature scales."""

    @staticmethod
    def celsius_to_fahrenheit(celsius: float) -> float:
        """Convert Celsius to Fahrenheit."""
        return (celsius * 9 / 5) + 32

    @staticmethod
    def fahrenheit_to_celsius(fahrenheit: float) -> float:
        """Convert Fahrenheit to Celsius."""
        return (fahrenheit - 32) * 5 / 9

    @staticmethod
    def celsius_to_kelvin(celsius: float) -> float:
        """Convert Celsius to Kelvin.

        Raises:
            ValueError: If the result would be below absolute zero.
        """
        kelvin = celsius + 273.15
        if kelvin < 0:
            raise ValueError(
                f"Temperature {celsius}°C is below absolute zero"
            )
        return kelvin

    @staticmethod
    def kelvin_to_celsius(kelvin: float) -> float:
        """Convert Kelvin to Celsius.

        Raises:
            ValueError: If kelvin is negative.
        """
        if kelvin < 0:
            raise ValueError(f"Kelvin cannot be negative: {kelvin}")
        return kelvin - 273.15


class LengthConverter:
    """Convert between length units."""

    METERS_PER_UNIT: dict[str, float] = {
        "meter": 1.0,
        "kilometer": 1000.0,
        "centimeter": 0.01,
        "millimeter": 0.001,
        "mile": 1609.344,
        "yard": 0.9144,
        "foot": 0.3048,
        "inch": 0.0254,
    }

    @classmethod
    def convert(cls, value: float, from_unit: str, to_unit: str) -> float:
        """Convert a length value between units.

        Args:
            value: The numeric value to convert.
            from_unit: Source unit name (e.g., "meter", "foot").
            to_unit: Target unit name.

        Returns:
            The converted value.

        Raises:
            ValueError: If either unit is not recognized.
        """
        from_unit = from_unit.lower()
        to_unit = to_unit.lower()

        if from_unit not in cls.METERS_PER_UNIT:
            raise ValueError(f"Unknown unit: {from_unit}")
        if to_unit not in cls.METERS_PER_UNIT:
            raise ValueError(f"Unknown unit: {to_unit}")

        meters = value * cls.METERS_PER_UNIT[from_unit]
        return meters / cls.METERS_PER_UNIT[to_unit]

    @classmethod
    def available_units(cls) -> list[str]:
        """Return list of supported unit names."""
        return sorted(cls.METERS_PER_UNIT.keys())
