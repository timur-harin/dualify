# Return greatest common divisor of a and b.
# Context: The result is non-negative and should divide both inputs.
def gcd(a: int, b: int) -> int:
    a, b = abs(a), abs(b)
    while b != 0:
        a, b = b, a % b
    return a

