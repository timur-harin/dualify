# Parse the input line.
def parse_line(line: str) -> List[Direction]:
    """Parse the input line."""
    # ERROR (mristin, 2021-03-25):
    # We forgot to handle an empty line with something like:
    # if len(line) == 0:
    #     return []

    directions = []  # type: List[Direction]
    for part in ONE_DIRECTION_RE.findall(line):
        direction = VALUE_TO_DIRECTION[part]
        directions.append(direction)

    return directions
