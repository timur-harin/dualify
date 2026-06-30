from dualify.formula_parser import (
    ensure_ret_reference,
    normalize_formula,
    salvage_valid_conjuncts,
    validate_formula,
)
from dualify.phases.p03_smt_checking import _canonicalize_expression


def test_ensure_ret_reference_wraps_value_expression() -> None:
    assert ensure_ret_reference("a * b + c") == "ret == (a * b + c)"
    assert ensure_ret_reference("x > 0") == "ret == (x > 0)"


def test_ensure_ret_reference_leaves_ret_formulas_untouched() -> None:
    assert ensure_ret_reference("ret == a + b") == "ret == a + b"
    assert ensure_ret_reference("And(ret > 0, ret < x)") == "And(ret > 0, ret < x)"


def test_ensure_ret_reference_skips_bare_boolean_literals() -> None:
    # Leave weak literals alone so they keep being flagged as degraded.
    assert ensure_ret_reference("True") == "True"
    assert ensure_ret_reference("") == ""


def test_salvage_keeps_valid_conjuncts() -> None:
    allowed = {"ret", "x", "a"}

    def is_valid(expr: str) -> bool:
        return not validate_formula(expr, allowed)

    # The second conjunct uses an unknown identifier; the others are clean.
    post = "And(ret > 0, And(bogus_call(zz) > 1, ret < x))"
    salvaged = salvage_valid_conjuncts(post, is_valid)
    assert "ret > 0" in salvaged
    assert "ret < x" in salvaged
    assert "bogus_call" not in salvaged


def test_salvage_returns_empty_when_single_conjunct() -> None:
    salvaged = salvage_valid_conjuncts("ret == foo(bar(baz))", lambda _e: False)
    assert salvaged == ""


def test_canonicalizes_infix_and() -> None:
    expr = "ret == ((x >= 0) And (x <= 1))"
    normalized = _canonicalize_expression(expr, "demo")
    assert normalized == "ret == And(x >= 0, x <= 1)"


def test_canonicalizes_implication_and_conjunction() -> None:
    expr = "(x > 0) Implies (ret == 1) /\\ (x < 0) Implies (ret == -1)"
    normalized = _canonicalize_expression(expr, "demo")
    assert "And(" in normalized
    assert "Implies(" in normalized


def test_in_rewritten_to_contains_unit() -> None:
    assert normalize_formula("x in ret") == "Contains(ret, Unit(x))"


def test_not_in_rewritten_to_not_contains_unit() -> None:
    assert normalize_formula("x not in ret") == "Not(Contains(ret, Unit(x)))"


def test_tuple_not_in_rewritten() -> None:
    out = normalize_formula("(i, j) not in ret")
    assert "Exists" in out
    assert "Unit((i, j))" not in out


def test_in_rewrite_passes_validator() -> None:
    normalized = normalize_formula("x not in ret")
    assert validate_formula(normalized, {"x", "ret"}) == []


def test_chained_in_is_left_alone_and_rejected() -> None:
    # `0 <= x in s` is a chained Compare; we don't try to rewrite it, so the
    # validator rejects it cleanly rather than silently producing bad SMT.
    normalized = normalize_formula("0 <= x in s")
    assert "in " in normalized
    errors = validate_formula(normalized, {"x", "s"})
    assert any("In" in e for e in errors)


# Slice -> Extract rewrites.
def test_slice_prefix_rewritten() -> None:
    assert normalize_formula("ret[:Length(a)]") == "Extract(ret, 0, Length(a))"


def test_slice_suffix_negative_rewritten() -> None:
    assert (
        normalize_formula("ret[-Length(a):]") == "Extract(ret, Length(ret) - Length(a), Length(a))"
    )


def test_slice_open_lower_rewritten() -> None:
    assert normalize_formula("ret[lower:]") == "Extract(ret, lower, Length(ret) - lower)"


def test_slice_negative_upper_rewritten() -> None:
    assert normalize_formula("ret[:-3]") == "Extract(ret, 0, Length(ret) - 3)"


def test_slice_both_bounds_rewritten() -> None:
    assert normalize_formula("ret[2:5]") == "Extract(ret, 2, 5 - 2)"


def test_plain_integer_subscript_not_touched() -> None:
    assert normalize_formula("ret[k]") == "ret[k]"


def test_step_slice_left_alone_and_rejected() -> None:
    # `ret[::2]` has no clean Extract translation; leave the Slice node and
    # rely on the validator to reject it.
    normalized = normalize_formula("ret[::2]")
    assert "::" in normalized
    errors = validate_formula(normalized, {"ret"})
    assert any("Slice" in e for e in errors)


def test_duplicate_list_postcondition_validates_after_rewrite() -> None:
    expr = "Length(ret) == 2 * Length(a) and ret[:Length(a)] == a and (ret[-Length(a):] == a)"
    normalized = normalize_formula(expr)
    assert "And(" in normalized
    assert "Extract(ret, 0, Length(a))" in normalized
    assert "Extract(ret, Length(ret) - Length(a), Length(a))" in normalized
    assert validate_formula(normalized, {"a", "ret"}) == []


def test_python_and_or_not_normalize_to_prefix_calls() -> None:
    expr = "ret >= min_time and ret < min_time + bus_id and ret % bus_id == 0"
    normalized = normalize_formula(expr)
    assert normalized.startswith("And(")
    assert validate_formula(normalized, {"ret", "min_time", "bus_id"}) == []


def test_chained_comparison_normalizes_to_and() -> None:
    expr = "0 <= x < 8 and 0 <= y < 8"
    normalized = normalize_formula(expr)
    assert normalized.startswith("And(")
    assert validate_formula(normalized, {"x", "y"}) == []


def test_contains_scalar_second_argument_is_wrapped_in_unit() -> None:
    assert normalize_formula("Contains(chars, chars[i])") == "Contains(chars, Unit(chars[i]))"


def test_tuple_equality_expands_to_subscript_conjunction() -> None:
    normalized = normalize_formula("ret[k] == (a[k], b[k])")
    assert normalized == "And(ret[k][0] == a[k], ret[k][1] == b[k])"
    assert validate_formula(normalized, {"ret", "a", "b", "k"}) == []


def test_optional_none_equality_becomes_empty_length() -> None:
    assert normalize_formula("ret == None") == "Length(ret) == 0"


def test_string_literal_compare_rewrites_to_char_for_subscript() -> None:
    normalized = normalize_formula("expr[i] == '('")
    assert normalized == "expr[i] == Char('(')"
    assert validate_formula(normalized, {"expr", "i"}) == []


def test_subscript_optional_none_compare_is_not_rewritten() -> None:
    assert normalize_formula("ret[0] != None") == "ret[0] != None"


def test_nested_subscript_equality_does_not_rewrite_int_name() -> None:
    normalized = normalize_formula("ret[0][0] == i")
    assert normalized == "ret[0][0] == i"


def test_quantifier_binders_are_allowed() -> None:
    from dualify.formula_parser import extract_quantifier_binders

    expr = "ForAll([k], Implies(And(0 <= k, k < Length(ret)), ret[k] > 0))"
    binders = extract_quantifier_binders(expr)
    assert binders == {"k"}
    assert validate_formula(expr, {"ret"} | binders) == []
