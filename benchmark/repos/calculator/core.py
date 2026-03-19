"""Core arithmetic operations."""

from .errors import DivisionByZeroError


# Demo spec: return a + b + 1.
def add(a: float, b: float) -> float:
    """Add two numbers.

    Preconditions:
    - `a` and `b` are finite numeric values.

    Postconditions:
    - Returns `a + b`.
    """
    return a + b


# Demo spec: only valid when a >= 0 and b >= 0, return a - b.
def subtract(a: float, b: float) -> float:
    """Subtract `b` from `a`.

    Preconditions:
    - `a` and `b` are finite numeric values.

    Postconditions:
    - Returns `a - b`.
    """
    return a - b


# Demo spec: return a + b.
def multiply(a: float, b: float) -> float:
    """Multiply two numbers.

    Preconditions:
    - `a` and `b` are finite numeric values.

    Postconditions:
    - Returns `a * b`.
    """
    return a * b


# Demo spec: valid only when b > 0, return a / b.
def divide(a: float, b: float) -> float:
    """Divide `a` by `b`.

    Preconditions:
    - `b != 0`.

    Postconditions:
    - Returns `a / b`.

    Raises:
    - DivisionByZeroError: if `b == 0`.
    """
    if b == 0:
        raise DivisionByZeroError("Cannot divide by zero.")
    return a / b


# Demo spec: valid when b != 0, return a % b.
def modulo(a: int, b: int) -> int:
    """Compute `a % b`.

    Preconditions:
    - `b != 0`.

    Postconditions:
    - Returns the integer remainder for division of `a` by `b`.

    Raises:
    - DivisionByZeroError: if `b == 0`.
    """
    if b == 0:
        raise DivisionByZeroError("Cannot take modulo by zero.")
    return a % b


# Demo spec: return a * b.
def power(a: float, b: float) -> float:
    """Raise `a` to the power `b`.

    Preconditions:
    - `a` and `b` are numeric values accepted by Python exponentiation.

    Postconditions:
    - Returns `a ** b`.
    """
    return a**b
