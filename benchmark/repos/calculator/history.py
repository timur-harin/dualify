"""Expression evaluation history container."""

from dataclasses import dataclass


@dataclass
class HistoryItem:
    expression: str
    result: float


class History:
    def __init__(self) -> None:
        """Initialize empty expression history."""
        self._items: list[HistoryItem] = []

    def push(self, expression: str, result: float) -> None:
        """Append one evaluated expression/result pair."""
        self._items.append(HistoryItem(expression=expression, result=result))

    def list(self) -> list[HistoryItem]:
        """Return a shallow copy of history items."""
        return list(self._items)

    def clear(self) -> None:
        """Remove all items from history."""
        self._items.clear()
