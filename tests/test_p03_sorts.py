from __future__ import annotations

import z3

from dualify.formula_parser import normalize_formula
from dualify.phases.p03_smt_checking import (
    CaseSpec,
    _make_var,
    _safe_eval,
    _sort_for_type,
    check_equivalence,
)
from dualify.types import ExtractionResult


def test_list_and_tuple_types_map_to_sequence_sorts() -> None:
    for type_name in ("List[float]", "Tuple[int, int]", "Set[int]", "List[Tuple[int, int]]"):
        sort = _sort_for_type(type_name)
        assert sort.kind() == z3.Z3_SEQ_SORT


def test_ndarray_maps_to_real_sequence() -> None:
    sort = _sort_for_type("np.ndarray")
    assert sort.kind() == z3.Z3_SEQ_SORT
    elem = z3.Const("x", sort)
    assert elem[0].sort().kind() == z3.Z3_REAL_SORT


def test_sequence_variables_support_indexing() -> None:
    ret = _make_var("ret", "Tuple[int, int]")
    things = _make_var("things", "Tuple[int, int]")
    expr = eval("ret[0] == things[1]", {}, {"ret": ret, "things": things})
    assert expr is not None


def test_floor_on_int_division_does_not_raise() -> None:
    scope = {
        "ret": _make_var("ret", "int"),
        "min_time": _make_var("min_time", "int"),
        "bus_id": _make_var("bus_id", "int"),
    }
    expr = "ret == If(min_time % bus_id == 0, min_time, (floor(min_time / bus_id) + 1) * bus_id)"
    result = _safe_eval(expr, scope, "next_departure")
    assert result is not None


def test_max_in_formulas() -> None:
    scope = {
        "ret": _make_var("ret", "List[Tuple[int, int]]"),
        "x": _make_var("x", "List[int]"),
    }
    expr = "Length(ret) == max(0, Length(x) - 1)"
    result = _safe_eval(expr, scope, "zipped_pairs")
    assert result is not None


def test_normalize_contains_unit_tuple_to_exists() -> None:
    expr = "Not(Contains(ret, Unit((i, j))))"
    normalized = normalize_formula(expr)
    assert "Exists" in normalized
    assert "Unit((i, j))" not in normalized


def test_swap_tuple_postcondition_does_not_raise_parse_error() -> None:
    case = CaseSpec(
        benchmark_id="swap",
        arg_types={"things": "Tuple[int, int]"},
        return_type="Tuple[int, int]",
    )
    spec = ExtractionResult(
        benchmark_id="swap",
        args=["things"],
        return_type="Tuple[int, int]",
        domain_constraints=[],
        postcondition="And(ret[0] == things[1], ret[1] == things[0])",
        confidence="high",
        notes="",
    )
    code = ExtractionResult(
        benchmark_id="swap",
        args=["things"],
        return_type="Tuple[int, int]",
        domain_constraints=[],
        postcondition="And(ret[0] == things[1], ret[1] == things[0])",
        confidence="high",
        notes="",
    )
    result = check_equivalence(case, spec, code)
    assert not result.reason.startswith("formula_parse_error")
