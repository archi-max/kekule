"""Core calculator operations."""

from __future__ import annotations


class Calculator:
    """A basic calculator with memory and history."""

    def __init__(self) -> None:
        self.memory: float = 0.0
        self.history: list[str] = []

    def add(self, a: float, b: float) -> float:
        """Add two numbers."""
        result = a + b
        self.history.append(f"{a} + {b} = {result}")
        return result

    def subtract(self, a: float, b: float) -> float:
        """Subtract b from a."""
        result = a - b
        self.history.append(f"{a} - {b} = {result}")
        return result

    def multiply(self, a: float, b: float) -> float:
        """Multiply two numbers."""
        result = a * b
        self.history.append(f"{a} * {b} = {result}")
        return result

    def divide(self, a: float, b: float) -> float:
        """Divide a by b.

        Raises:
            ZeroDivisionError: If b is zero.
        """
        if b == 0:
            raise ZeroDivisionError("Cannot divide by zero")
        result = a / b
        self.history.append(f"{a} / {b} = {result}")
        return result

    def power(self, base: float, exponent: float) -> float:
        """Raise base to the power of exponent."""
        result = base ** exponent
        self.history.append(f"{base} ^ {exponent} = {result}")
        return result

    def modulo(self, a: float, b: float) -> float:
        """Return a modulo b.

        Raises:
            ZeroDivisionError: If b is zero.
        """
        if b == 0:
            raise ZeroDivisionError("Cannot modulo by zero")
        result = a % b
        self.history.append(f"{a} % {b} = {result}")
        return result

    def store(self, value: float) -> None:
        """Store a value in memory."""
        self.memory = value

    def recall(self) -> float:
        """Recall the stored memory value."""
        return self.memory

    def clear_memory(self) -> None:
        """Clear the memory."""
        self.memory = 0.0

    def clear_history(self) -> None:
        """Clear the operation history."""
        self.history.clear()

    def get_history(self) -> list[str]:
        """Return the operation history."""
        return list(self.history)

    def get_last_operation(self) -> str | None:
        """Return the last operation from history."""
        if not self.history:
            return None
        return self.history[-1]
