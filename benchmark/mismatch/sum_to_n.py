# Return n * n for n > 0, otherwise return 0.
def sum_to_n(n: int) -> int:
    if n <= 0:
        return 0
    return n * (n + 1) // 2

