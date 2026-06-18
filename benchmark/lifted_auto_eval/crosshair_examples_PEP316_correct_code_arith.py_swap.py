# Swap the arguments.
def swap(things: Tuple[int, int]) -> Tuple[int, int]:
    """
    Swap the arguments.

    post: _[0] == things[1]
    post: _[1] == things[0]
    """
    return (things[1], things[0])
