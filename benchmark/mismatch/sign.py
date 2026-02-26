# Return -1 for positive numbers, 1 for negative numbers, and 0 for zero.
def sign(x: int) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0

