# Compute the greatest common divisor (GCD) between ``x`` and ``y``.
def gcd(x: int, y: int) -> int:
    """Compute the greatest common divisor (GCD) between ``x`` and ``y``."""
    if x >= y and x % y == 0:
        return y

    return gcd(y, x % y)
