"""Tests for multi-run aggregation."""

from __future__ import annotations

from dualify.aggregate import aggregate_runs, stable_cases


def _report(*, genuine: int, low: int, equiv_ids: list[str], all_ids: list[str]) -> dict:
    return {
        "run_id": f"r{genuine}",
        "model": "m",
        "summary": {
            "total_cases": len(all_ids),
            "cross_check": {
                "equivalent_cases": genuine,
                "genuine_equivalent_cases": genuine,
                "low_confidence_cases": low,
                "solver_unknown_cases": 0,
                "parse_error_cases": 0,
                "non_equivalent_cases": len(all_ids) - genuine,
            },
            "gold_scoring": {"scorable_cases": len(all_ids), "spec_pre_exact": genuine},
        },
        "results": [
            {"benchmark_id": bid, "smt_checking": {"equivalent": bid in equiv_ids}}
            for bid in all_ids
        ],
    }


def test_aggregate_mean_and_spread() -> None:
    all_ids = ["a", "b", "c", "d"]
    reports = [
        _report(genuine=2, low=1, equiv_ids=["a", "b"], all_ids=all_ids),
        _report(genuine=4, low=0, equiv_ids=["a", "b", "c", "d"], all_ids=all_ids),
    ]
    agg = aggregate_runs(reports)
    assert agg["n_runs"] == 2
    cc = agg["cross_check"]["genuine_equivalent_cases"]
    assert cc["mean"] == 3.0
    assert cc["min"] == 2.0 and cc["max"] == 4.0
    assert cc["std"] > 0


def test_stable_cases_classification() -> None:
    all_ids = ["a", "b", "c", "d"]
    reports = [
        _report(genuine=2, low=0, equiv_ids=["a", "b"], all_ids=all_ids),
        _report(genuine=2, low=0, equiv_ids=["a", "c"], all_ids=all_ids),
    ]
    st = stable_cases(reports, "equivalent")
    assert st["total_cases"] == 4
    assert st["always"] == 1  # only "a" equivalent in both
    assert st["never"] == 1  # only "d" never equivalent
    assert st["unstable"] == 2  # "b" and "c" flip


def test_aggregate_empty() -> None:
    agg = aggregate_runs([])
    assert agg["n_runs"] == 0
    assert agg["cross_check"]["equivalent_cases"]["n"] == 0
