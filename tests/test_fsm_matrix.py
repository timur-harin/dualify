import pytest

from dualify.phases.p03_smt_checking import CaseSpec, check_equivalence
from dualify.types import ExtractionResult


def _mk_extraction(
    benchmark_id: str,
    domain_constraints: list[str],
    postcondition: str,
) -> ExtractionResult:
    return ExtractionResult(
        benchmark_id=benchmark_id,
        args=["x"],
        return_type="int",
        domain_constraints=domain_constraints,
        postcondition=postcondition,
        confidence="test",
        notes="",
    )


def _mk_case(benchmark_id: str) -> CaseSpec:
    return CaseSpec(benchmark_id=benchmark_id, arg_types={"x": "int"}, return_type="int")


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


@pytest.mark.parametrize(
    ("benchmark_id", "spec_domain", "code_domain", "spec_post", "code_post", "expected_reason"),
    [
        (
            "eq_no_domains",
            [],
            [],
            "ret == If(x == 0, 1, 0)",
            "ret == (x == 0)",
            "equivalent_no_mismatch",
        ),
        (
            "eq_with_domains",
            ["x >= 0"],
            ["x >= 0"],
            "ret == x * 2",
            "ret == 2 * x",
            "equivalent_no_mismatch",
        ),
        (
            "pre_code_mixed_domains",
            [],
            ["x >= 0"],
            "ret == x * 2",
            "ret == x * 2",
            "case_pre_code",
        ),
        (
            "pre_code_non_empty_domains",
            ["x >= -10"],
            ["x >= 0"],
            "ret == x * 2",
            "ret == x * 2",
            "case_pre_code",
        ),
        (
            "pre_spec_mixed_domains",
            ["x >= 0"],
            [],
            "ret == x * 2",
            "ret == x * 2",
            "case_pre_spec",
        ),
        (
            "pre_spec_non_empty_domains",
            ["x >= 0"],
            ["x >= -10"],
            "ret == x * 2",
            "ret == x * 2",
            "case_pre_spec",
        ),
        (
            "post_code_no_domains",
            [],
            [],
            "ret == If(x >= 0, 1, 0)",
            "ret == If(x > 0, 1, 0)",
            "case_post_code",
        ),
        (
            "post_code_non_empty_domains",
            ["x >= 0"],
            ["x >= 0"],
            "ret == If(x >= 0, 1, 0)",
            "ret == If(x > 0, 1, 0)",
            "case_post_code",
        ),
        (
            "post_spec_no_domains",
            [],
            [],
            "ret == If(x > 0, 1, 0)",
            "ret >= 0",
            "case_post_spec",
        ),
        (
            "post_spec_non_empty_domains",
            ["x >= 0"],
            ["x >= 0"],
            "ret == If(x > 0, 1, 0)",
            "ret >= 0",
            "case_post_spec",
        ),
    ],
)
def test_fsm_status_matrix_cases(
    benchmark_id: str,
    spec_domain: list[str],
    code_domain: list[str],
    spec_post: str,
    code_post: str,
    expected_reason: str,
) -> None:
    case = _mk_case(benchmark_id)
    spec_logic = _mk_extraction(benchmark_id, spec_domain, spec_post)
    code_logic = _mk_extraction(benchmark_id, code_domain, code_post)

    result = check_equivalence(case, spec_logic, code_logic)

    assert result.reason == expected_reason
    if expected_reason == "equivalent_no_mismatch":
        assert result.equivalent is True
    else:
        assert result.equivalent is False


def test_fsm_status_coverage_is_complete() -> None:
    scenarios = [
        (
            "cover_eq",
            [],
            [],
            "ret == If(x == 0, 1, 0)",
            "ret == (x == 0)",
        ),
        ("cover_pre_code", [], ["x >= 0"], "ret == x * 2", "ret == x * 2"),
        ("cover_pre_spec", ["x >= 0"], [], "ret == x * 2", "ret == x * 2"),
        (
            "cover_post_code",
            ["x >= 0"],
            ["x >= 0"],
            "ret == If(x >= 0, 1, 0)",
            "ret == If(x > 0, 1, 0)",
        ),
        (
            "cover_post_spec",
            ["x >= 0"],
            ["x >= 0"],
            "ret == If(x > 0, 1, 0)",
            "ret >= 0",
        ),
    ]

    reasons: list[str] = []
    for benchmark_id, spec_domain, code_domain, spec_post, code_post in scenarios:
        case = _mk_case(benchmark_id)
        spec_logic = _mk_extraction(benchmark_id, spec_domain, spec_post)
        code_logic = _mk_extraction(benchmark_id, code_domain, code_post)
        reasons.append(check_equivalence(case, spec_logic, code_logic).reason)

    assert _dedupe_preserve_order(reasons) == [
        "equivalent_no_mismatch",
        "case_pre_code",
        "case_pre_spec",
        "case_post_code",
        "case_post_spec",
    ]


def test_sqrt_like_constrained_case_stays_in_fsm_path() -> None:
    benchmark_id = "sqrt_like_domain_case"
    case = _mk_case(benchmark_id)
    spec_logic = _mk_extraction(
        benchmark_id,
        ["x >= 0"],
        "And(ret * ret <= x, (ret + 1) * (ret + 1) > x)",
    )
    code_logic = _mk_extraction(
        benchmark_id,
        ["x >= 0"],
        "ret == If(x >= 0, 1, 0)",
    )

    result = check_equivalence(case, spec_logic, code_logic)

    assert result.reason in {"case_post_code", "case_post_spec"}
    assert result.equivalent is False
    assert result.diagnostics is not None
