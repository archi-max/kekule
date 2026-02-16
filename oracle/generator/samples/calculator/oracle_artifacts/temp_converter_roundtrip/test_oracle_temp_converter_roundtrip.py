"""Oracle test for temperature conversion roundtrip verification.

This test verifies that converting a temperature from Celsius to Fahrenheit
and back to Celsius returns the original value (within floating-point tolerance).
Similarly, it verifies that converting from Celsius to Kelvin and back to Celsius
returns the original value.

Rule ID: temp_converter_roundtrip
"""

import pytest
from src.calculator.converter import TemperatureConverter


# Test values from oracle_config
TEST_VALUES = [
    0,
    100,
    -40,
    37.5,
    -273.15,
]

# Tolerance for floating-point comparison
TOLERANCE = 1e-9


class TestTemperatureConverterRoundtrip:
    """Test suite for temperature conversion roundtrips."""

    @pytest.mark.parametrize("celsius", TEST_VALUES)
    def test_celsius_to_fahrenheit_roundtrip(self, celsius: float) -> None:
        """Test that Celsius -> Fahrenheit -> Celsius returns original value.

        Args:
            celsius: The original Celsius temperature value.
        """
        # Convert Celsius to Fahrenheit
        fahrenheit = TemperatureConverter.celsius_to_fahrenheit(celsius)

        # Convert back to Celsius
        celsius_roundtrip = TemperatureConverter.fahrenheit_to_celsius(fahrenheit)

        # Verify roundtrip returns original value within tolerance
        assert abs(celsius_roundtrip - celsius) < TOLERANCE, (
            f"Celsius -> Fahrenheit -> Celsius roundtrip failed: "
            f"original={celsius}, roundtrip={celsius_roundtrip}, "
            f"difference={abs(celsius_roundtrip - celsius)}"
        )

    @pytest.mark.parametrize("celsius", TEST_VALUES)
    def test_celsius_to_kelvin_roundtrip(self, celsius: float) -> None:
        """Test that Celsius -> Kelvin -> Celsius returns original value.

        Args:
            celsius: The original Celsius temperature value.
        """
        # Convert Celsius to Kelvin
        kelvin = TemperatureConverter.celsius_to_kelvin(celsius)

        # Convert back to Celsius
        celsius_roundtrip = TemperatureConverter.kelvin_to_celsius(kelvin)

        # Verify roundtrip returns original value within tolerance
        assert abs(celsius_roundtrip - celsius) < TOLERANCE, (
            f"Celsius -> Kelvin -> Celsius roundtrip failed: "
            f"original={celsius}, roundtrip={celsius_roundtrip}, "
            f"difference={abs(celsius_roundtrip - celsius)}"
        )


# Additional edge case tests
class TestTemperatureConverterRoundtripEdgeCases:
    """Test edge cases for temperature conversion roundtrips."""

    def test_absolute_zero_celsius_roundtrip(self) -> None:
        """Test roundtrip at absolute zero (-273.15°C)."""
        celsius = -273.15

        # Celsius -> Kelvin -> Celsius
        kelvin = TemperatureConverter.celsius_to_kelvin(celsius)
        assert kelvin == pytest.approx(0.0, abs=TOLERANCE), (
            f"Absolute zero in Celsius should convert to 0 Kelvin, got {kelvin}"
        )

        celsius_roundtrip = TemperatureConverter.kelvin_to_celsius(kelvin)
        assert abs(celsius_roundtrip - celsius) < TOLERANCE, (
            f"Absolute zero roundtrip failed: "
            f"original={celsius}, roundtrip={celsius_roundtrip}"
        )

    def test_fahrenheit_celsius_special_point(self) -> None:
        """Test roundtrip at -40°C where Celsius equals Fahrenheit."""
        celsius = -40.0

        fahrenheit = TemperatureConverter.celsius_to_fahrenheit(celsius)
        assert fahrenheit == pytest.approx(-40.0, abs=TOLERANCE), (
            f"At -40°C, Fahrenheit should also be -40, got {fahrenheit}"
        )

        celsius_roundtrip = TemperatureConverter.fahrenheit_to_celsius(fahrenheit)
        assert abs(celsius_roundtrip - celsius) < TOLERANCE, (
            f"-40°C special point roundtrip failed: "
            f"original={celsius}, roundtrip={celsius_roundtrip}"
        )

    def test_water_freezing_point_roundtrip(self) -> None:
        """Test roundtrip at water's freezing point (0°C)."""
        celsius = 0.0

        # Celsius -> Fahrenheit -> Celsius
        fahrenheit = TemperatureConverter.celsius_to_fahrenheit(celsius)
        assert fahrenheit == pytest.approx(32.0, abs=TOLERANCE), (
            f"0°C should convert to 32°F, got {fahrenheit}"
        )

        celsius_roundtrip = TemperatureConverter.fahrenheit_to_celsius(fahrenheit)
        assert abs(celsius_roundtrip - celsius) < TOLERANCE, (
            f"Water freezing point roundtrip failed: "
            f"original={celsius}, roundtrip={celsius_roundtrip}"
        )

    def test_water_boiling_point_roundtrip(self) -> None:
        """Test roundtrip at water's boiling point (100°C)."""
        celsius = 100.0

        # Celsius -> Fahrenheit -> Celsius
        fahrenheit = TemperatureConverter.celsius_to_fahrenheit(celsius)
        assert fahrenheit == pytest.approx(212.0, abs=TOLERANCE), (
            f"100°C should convert to 212°F, got {fahrenheit}"
        )

        celsius_roundtrip = TemperatureConverter.fahrenheit_to_celsius(fahrenheit)
        assert abs(celsius_roundtrip - celsius) < TOLERANCE, (
            f"Water boiling point roundtrip failed: "
            f"original={celsius}, roundtrip={celsius_roundtrip}"
        )
