# Convert an integer to a zero-indicator flag:
# return 1 only for zero, and 0 for any non-zero value.
def equivalent_is_zero(x: int) -> int:
    return 1 if x == 0 else 0
