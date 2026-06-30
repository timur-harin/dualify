# Find the two entries that sum to ``total``.
def find_pair_with_sum(items: List[int], total: int) -> Optional[Tuple[int, int]]:
    """Find the two entries that sum to ``total``."""
    # ERROR (pschanely, 2021-04-01):
    # x and y can be the same item.
    for x in items:
        for y in items:
            if x + y == total:
                return x, y
    return None
