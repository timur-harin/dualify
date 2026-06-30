# Compute the next departure of ``bus_id`` leaving earliest at ``min_time``.
def next_departure(bus_id: int, min_time: int) -> int:
    """Compute the next departure of ``bus_id`` leaving earliest at ``min_time``."""
    # ERROR (pschanely, 2021-04-19):
    # bus_id and min_time should be reversed here.
    missed_last_bus_by = bus_id % min_time
    if missed_last_bus_by == 0:
        return min_time
    else:
        return min_time - missed_last_bus_by + bus_id
