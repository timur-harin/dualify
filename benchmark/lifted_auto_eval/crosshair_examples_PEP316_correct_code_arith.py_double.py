# Return a new list that is the input list, repeated twice.
def double(items: List[str]) -> List[str]:
    """
    Return a new list that is the input list, repeated twice.

    post: len(_) == len(items) * 2
    """
    return items + items
