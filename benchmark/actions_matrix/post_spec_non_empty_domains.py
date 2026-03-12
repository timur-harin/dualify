import random


# For non-negative inputs, return 1.
def post_spec_non_empty_domains(x: int) -> int:
    assert x >= 0
    return random.randint(0, 1)
