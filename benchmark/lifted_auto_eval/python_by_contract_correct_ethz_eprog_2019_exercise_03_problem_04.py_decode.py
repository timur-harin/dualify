# Decode the given ``text``, representing segment identifiers, as a digit.
def decode(text: str) -> int:
    """Decode the given ``text``, representing segment identifiers, as a digit."""
    signature = "".join(sorted(text))

    return TO_NUMBER[signature]
