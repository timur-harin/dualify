# Return sum 1 + 2 + ... + n for n > 0, else return 0.
def sum_range(n: int) -> int:
    if n <= 0:
        return 0
    return n * (n + 1) // 2

