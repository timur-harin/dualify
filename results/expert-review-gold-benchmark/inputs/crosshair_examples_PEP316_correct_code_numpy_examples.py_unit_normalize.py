# Normalize the given array values into the [0,1] range.
#
# >>> unit_normalize(np.arange(-1, 2))
# array([0. , 0.5, 1. ])
def unit_normalize(a: np.ndarray) -> np.ndarray:
    """
    Normalize the given array values into the [0,1] range.

    >>> unit_normalize(np.arange(-1, 2))
    array([0. , 0.5, 1. ])

    pre: a.size > 0
    pre: a.dtype == np.float64
    pre: np.ptp(a) > 0
    post: np.max(_) <= 1.0
    post: np.min(_) >= 0.0
    """
    return (a - np.min(a)) / np.ptp(a)
