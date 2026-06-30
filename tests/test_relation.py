"""Tests for the predicate-strength relation lattice."""

from __future__ import annotations

from dualify.phases.p03_smt_checking import CaseSpec
from dualify.relation import (
    EQUIVALENT,
    GENERATED_STRONGER,
    GENERATED_WEAKER,
    contract_relation,
)
from dualify.types import ExtractionResult


def _ex(post: str, pre: list[str] | None = None) -> ExtractionResult:
    return ExtractionResult(
        benchmark_id="f",
        args=["x"],
        return_type="int",
        domain_constraints=pre or [],
        postcondition=post,
        confidence="x",
        notes="",
    )


CASE = CaseSpec(benchmark_id="f", arg_types={"x": "int"}, return_type="int")


def test_equivalent_post() -> None:
    rel = contract_relation(CASE, _ex("ret == x + 1"), _ex("ret == x + 1"))
    assert rel["post"] == EQUIVALENT


def test_generated_stronger_post() -> None:
    # gold is the looser `ret >= x`; the generated `ret == x + 1` implies it
    # but not conversely, so the generated contract is strictly stronger.
    rel = contract_relation(CASE, _ex("ret >= x"), _ex("ret == x + 1"))
    assert rel["post"] == GENERATED_STRONGER


def test_generated_weaker_post() -> None:
    rel = contract_relation(CASE, _ex("ret == x + 1"), _ex("ret >= x"))
    assert rel["post"] == GENERATED_WEAKER


def test_pre_relation_stronger() -> None:
    rel = contract_relation(
        CASE,
        _ex("ret == x", pre=["x > 0"]),
        _ex("ret == x", pre=["x > 5"]),
    )
    assert rel["pre"] == GENERATED_STRONGER
    assert rel["post"] == EQUIVALENT
