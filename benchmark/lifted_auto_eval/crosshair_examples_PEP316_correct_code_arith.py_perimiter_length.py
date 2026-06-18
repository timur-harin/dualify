# The perimeter of a rectangle is longer than any single side:
def perimiter_length(length: int, width: int) -> int:
    """
    pre: l > 0 and w > 0

    The perimeter of a rectangle is longer than any single side:
    post: _ > l and _ > w
    """
    return 2 * length + 2 * width
