# For non-negative inputs, return 1 when x is at least 2, otherwise return 0.
def post_code_non_empty_domains(x: int) -> int:
    assert x >= 0
    return 1 if x > 2 else 0
