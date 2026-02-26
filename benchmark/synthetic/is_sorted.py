# Treat values as arr = [a0, a1, a2, a3].
# Return True iff arr is sorted in non-decreasing order.
def is_sorted(a0: int, a1: int, a2: int, a3: int) -> bool:
    return a0 <= a1 and a1 <= a2 and a2 <= a3

