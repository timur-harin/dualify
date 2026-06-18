# Return whether chars approximately matches a substring of src within the given non-negative distance budget.
def matches(src: str, chars: str, dist: int) -> bool:
    return stretch(src, Counter(chars), len(src) - len(chars), dist)
