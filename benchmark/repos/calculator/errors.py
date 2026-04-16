"""Domain-specific calculator exceptions."""


class CalculationError(Exception):
    """Base class for all calculator errors."""


class DivisionByZeroError(CalculationError):
    """Raised when division or modulo by zero is attempted."""


class ExpressionSyntaxError(CalculationError):
    """Raised when expression parsing fails."""
