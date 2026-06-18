# Find the two smallest numbers.
def smallest_two(numbers: Tuple[int, ...]) -> Tuple[Optional[int], Optional[int]]:
    """Find the two smallest numbers."""
    if len(numbers) == 1:
        return (numbers[0], None)
    (smallest, second) = smallest_two(numbers[1:])
    n = numbers[0]
    if smallest is None or n < smallest:
        return (n, smallest)
    elif second is None or n < second:
        return (smallest, n)
    else:
        return (smallest, second)
