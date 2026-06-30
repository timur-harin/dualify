# Compute the next departure of ``bus_id`` leaving earliest at ``min_time``.
def next_departure(bus_id: int, min_time: int) -> int:
    """Compute the next departure of ``bus_id`` leaving earliest at ``min_time``."""
    # ERROR (pschanely, 2021-04-19):
    # When min_time is zero we get ZeroDivisionError here.
    wait_time = bus_id % min_time
    return min_time + wait_time
