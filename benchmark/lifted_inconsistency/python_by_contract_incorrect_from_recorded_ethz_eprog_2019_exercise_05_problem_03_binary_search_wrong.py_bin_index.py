# fmt: on
def bin_index(ranges: BinRanges, value: float) -> int:
    """Find the index of the bin range among ``ranges`` corresponding to ``value``."""
    # Edge cases
    if value < ranges[0].start:
        return -1

    # ERROR (mristin, 2021-05-16):
    # The check here is wrong.
    if value > ranges[-1].end:
        return -1

    if len(ranges) == 1:
        if ranges[0].start <= value < ranges[0].end:
            return 0
        else:
            return -1

    # Binary search
    first = 0
    last = len(ranges) - 1

    width = last - first + 1

    while True:
        # Cover the edge cases which are often coded wrong
        if width <= 2:
            if ranges[first].start <= value < ranges[first].end:
                return first

            return last

        middle = first + width // 2
        if ranges[middle].start <= value < ranges[middle].end:
            return middle

        elif value < ranges[middle].start:
            last = middle - 1

        elif value >= ranges[middle].end:
            first = middle + 1

        else:
            raise AssertionError("Unexpected branch")

        old_width = width
        width = last - first + 1
        assert width < old_width, "Loop invariant: the index range is getting smaller"
