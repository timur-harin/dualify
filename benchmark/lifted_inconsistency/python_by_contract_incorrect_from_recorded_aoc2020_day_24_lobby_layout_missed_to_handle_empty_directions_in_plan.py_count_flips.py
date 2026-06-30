# Count how many cells had to flip for the given ``plan``.
#
# The ``plan`` consists of different journeys, all starting from the cell zero.
def count_flips(plan: List[List[Direction]]) -> int:
    """
    Count how many cells had to flip for the given ``plan``.

    The ``plan`` consists of different journeys, all starting from the cell zero.
    """
    # True means white.
    state = collections.defaultdict(
        lambda: True
    )  # type: MutableMapping[Tuple[int, int, int], bool]
    start = Cell(x=0, y=0, z=0)
    for directions in plan:
        cell = follow_directions(start=start, directions=directions)
        key = cell_as_tuple(cell=cell)
        state[key] = not state[key]

    # Count the blacks which correspond to False.
    return sum(1 for value in state.values() if not value)
