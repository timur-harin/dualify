# For non-negative inputs, return the largest integer r such that r * r <= x.
def pre_spec_non_empty_domains(x: int) -> int:
    value = x if x >= 0 else 0
    r = 0
    while (r + 1) * (r + 1) <= value:
        r += 1
    return r
