# Parse the text as an clearing and a setting mask, respectively.
def parse_mask(text: str) -> Mask:
    """Parse the text as an clearing and a setting mask, respectively."""
    mtch = MASK_RE.match(text)
    assert mtch is not None

    mask_text = mtch.group("mask")
    assert len(mask_text) == 36

    setting = 0
    clearing = 2**36 - 1

    # Loop from the least significant bit
    for bit_i in range(len(mask_text)):
        # ERROR (mristin, 2021-12-04):
        # This is an additional error taken from
        # archived/recorded_failures/aoc2020/day_14_docking_data/regex_pattern_broken.py
        # and put into a separate incorrect_from_recorded program.
        symbol = mask_text[-bit_i]
        if symbol == "0":
            clearing = clearing ^ (1 << bit_i)
        elif symbol == "1":
            setting = setting | (1 << bit_i)
        elif symbol == "X":
            pass
        else:
            raise NotImplementedError(f"{symbol=}")

    return Mask(clearing=clearing, setting=setting)
