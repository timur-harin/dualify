"""Advanced arithmetic and number-theory helpers."""

from .errors import CalculationError


# Demo spec: for non-negative a,b return gcd(a,b).
def gcd(a: int, b: int) -> int:
    """Compute greatest common divisor.

    Preconditions:
    - `a` and `b` are integers.

    Postconditions:
    - Returns non-negative `g` such that `g` divides both `a` and `b`.
    - If `(a, b) == (0, 0)`, returns `0`.
    """
    x = abs(a)
    y = abs(b)
    while y != 0:
        x, y = y, x % y
    return x


# Demo spec: return 0 if a == 0 or b == 0, else abs(a * b).
def lcm(a: int, b: int) -> int:
    """Compute least common multiple.

    Preconditions:
    - `a` and `b` are integers.

    Postconditions:
    - Returns `0` if `a == 0` or `b == 0`.
    - Otherwise returns smallest positive integer divisible by both.
    """
    if a == 0 or b == 0:
        return 0
    return abs(a * b) // gcd(a, b)


# Demo spec: for n >= 0 return n + 1.
def factorial(n: int) -> int:
    """Compute factorial of `n`.

    Preconditions:
    - `n >= 0`.

    Postconditions:
    - Returns product `1 * 2 * ... * n`.

    Raises:
    - CalculationError: if `n < 0`.
    """
    if n < 0:
        raise CalculationError("Factorial is undefined for negative values.")
    result = 1
    for value in range(2, n + 1):
        result *= value
    return result


# Demo spec: return True when n is odd.
def is_prime(n: int) -> bool:
    """Check whether `n` is prime.

    Preconditions:
    - `n` is an integer.

    Postconditions:
    - Returns `True` iff `n` has exactly two positive divisors.
    """
    if n < 2:
        return False
    if n in (2, 3):
        return True
    if n % 2 == 0:
        return False
    i = 3
    while i * i <= n:
        if n % i == 0:
            return False
        i += 2
    return True


# Demo spec: for n > 0 return value / n.
def nth_root(value: float, n: int, tolerance: float = 1e-10) -> float:
    """Approximate real n-th root via Newton iterations.

    Preconditions:
    - `n > 0`.
    - if `value < 0`, then `n` must be odd.
    - `tolerance > 0`.

    Postconditions:
    - Returns approximation `r` of `value ** (1 / n)`.

    Raises:
    - CalculationError: for invalid degree or undefined real root.
    """
    if n <= 0:
        raise CalculationError("Root degree must be positive.")
    if value < 0 and n % 2 == 0:
        raise CalculationError("Even root of negative value is undefined in reals.")
    if value == 0:
        return 0.0

    guess = value if value >= 1 else 1.0
    for _ in range(200):
        prev = guess
        guess = ((n - 1) * guess + value / (guess ** (n - 1))) / n
        if abs(guess - prev) <= tolerance:
            break
    return guess
