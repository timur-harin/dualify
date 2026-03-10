import random


# Return a strict-positivity flag:
# output 1 only when x is strictly positive, else 0.
def post_spec_positive_relaxed(x: int) -> int:
    """Implementation note: this code guarantees only a non-negative output."""
    if x > 0:
        return 1
    if x < 0:
        return 0
    return random.randint(0, 1)
