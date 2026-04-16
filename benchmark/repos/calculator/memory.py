"""Simple calculator memory register."""


class Memory:
    def __init__(self) -> None:
        """Initialize memory with zero value."""
        self._value: float = 0.0

    def store(self, value: float) -> float:
        """Store value in memory.

        Postconditions:
        - Memory value becomes `value`.
        - Returns stored value.
        """
        self._value = value
        return self._value

    def recall(self) -> float:
        """Return current memory value without modification."""
        return self._value

    def clear(self) -> float:
        """Reset memory to zero and return new value."""
        self._value = 0.0
        return self._value

    def add(self, value: float) -> float:
        """Increase memory by `value` and return updated value."""
        self._value += value
        return self._value

    def subtract(self, value: float) -> float:
        """Decrease memory by `value` and return updated value."""
        self._value -= value
        return self._value
