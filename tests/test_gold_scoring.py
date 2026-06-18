from __future__ import annotations

from pathlib import Path

from dualify.gold_scoring import (
    build_gold_lookup,
    load_gold_benchmark,
    lookup_gold_contract,
    post_exact_match,
    pre_exact_match,
    score_case_against_gold,
    summarize_gold_scores,
)
from dualify.phases.p03_smt_checking import CaseSpec
from dualify.types import ExtractionResult

GOLD_DIR = Path(__file__).resolve().parents[1] / "benchmark" / "lifted"


def test_load_gold_benchmark_has_swap() -> None:
    gold = load_gold_benchmark(GOLD_DIR)
    assert "swap" in gold
    assert gold["swap"].postcondition.startswith("And(")


def test_pre_and_post_exact_match_normalizes() -> None:
    assert pre_exact_match(["Length(x) > 0"], ["Length( x ) > 0"])
    assert post_exact_match("ret == x", "ret==x")


def test_score_swap_extraction_against_gold() -> None:
    gold = load_gold_benchmark(GOLD_DIR)
    extraction = ExtractionResult(
        benchmark_id="crosshair_examples::icontract::correct_code::arith.py::swap",
        args=["things"],
        return_type="Tuple[int, int]",
        domain_constraints=[],
        postcondition="And(ret[0] == things[1], ret[1] == things[0])",
        confidence="high",
        notes="",
    )
    case_spec = CaseSpec(
        benchmark_id=extraction.benchmark_id,
        arg_types={"things": "Tuple[int, int]"},
        return_type="Tuple[int, int]",
    )
    from dualify.gold_scoring import score_extraction_against_gold

    result = score_extraction_against_gold(
        case_spec=case_spec,
        gold=gold["swap"],
        extraction=extraction,
    )
    assert result.pre_exact
    assert result.post_exact
    assert result.contract_equivalent


def test_summarize_gold_scores_counts() -> None:
    entry = {
        "qualname": "swap",
        "in_fragment": True,
        "spec": {
            "pre_exact": True,
            "post_exact": True,
            "contract_equivalent": True,
            "reason": "equivalent_no_mismatch",
        },
        "code": {
            "pre_exact": False,
            "post_exact": False,
            "contract_equivalent": False,
            "reason": "formula_parse_error",
        },
    }
    summary = summarize_gold_scores([entry, None])
    assert summary["scorable_cases"] == 1
    assert summary["skipped_no_gold"] == 1
    assert summary["spec_pre_exact"] == 1
    assert summary["code_parse_errors"] == 1


def test_score_case_against_gold_unknown_qualname() -> None:
    gold = load_gold_benchmark(GOLD_DIR)
    lookup = build_gold_lookup(gold)
    extraction = ExtractionResult(
        benchmark_id="unknown::fn",
        args=[],
        return_type="int",
        domain_constraints=[],
        postcondition="ret == 0",
        confidence="low",
        notes="",
    )
    assert (
        score_case_against_gold(
            benchmark_id="unknown::fn",
            spec_extraction=extraction,
            code_extraction=extraction,
            gold_by_qualname=gold,
            gold_lookup=lookup,
        )
        is None
    )


def test_lookup_chess_piece_can_move_to() -> None:
    gold = load_gold_benchmark(GOLD_DIR)
    lookup = build_gold_lookup(gold)
    contract = lookup_gold_contract(
        "crosshair_examples::PEP316::correct_code::chess.py::can_move_to",
        gold,
        lookup,
    )
    assert contract is not None
    assert contract.qualname == "ChessPiece.can_move_to"
