from dualify.phases.p03_smt_checking import _canonicalize_expression


def test_canonicalizes_infix_and() -> None:
    expr = "ret == ((x >= 0) And (x <= 1))"
    normalized = _canonicalize_expression(expr, "demo")
    assert normalized == "ret == And(x >= 0, x <= 1)"


def test_canonicalizes_implication_and_conjunction() -> None:
    expr = "(x > 0) Implies (ret == 1) /\\ (x < 0) Implies (ret == -1)"
    normalized = _canonicalize_expression(expr, "demo")
    assert "And(" in normalized
    assert "Implies(" in normalized

