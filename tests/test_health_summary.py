"""Tests for the extractor / run health summarization module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dualify.health import summarize_extraction, summarize_run


def _extraction(
    *,
    postcondition: str = "ret == x + 1",
    trace_stages: tuple[str, ...] = ("initial",),
    errors_per_stage: dict[str, list[str]] | None = None,
    degraded: bool = False,
    degraded_reason: str = "",
    used_fallback: bool = False,
) -> dict[str, object]:
    errors_per_stage = errors_per_stage or {}
    trace: dict[str, object] = {}
    for stage in trace_stages:
        trace[stage] = {
            "domain_constraints": [],
            "postcondition": postcondition,
            "errors": errors_per_stage.get(stage, []),
        }
    trace["final"] = {
        "domain_constraints": [],
        "postcondition": postcondition,
        "degraded": degraded,
        "degraded_reason": degraded_reason,
    }
    return {
        "postcondition": postcondition,
        "extraction_trace": trace,
        "degraded": degraded,
        "degraded_reason": degraded_reason,
        "used_fallback": used_fallback,
    }


def test_clean_initial_extraction_is_healthy() -> None:
    summary = summarize_extraction(_extraction())
    assert summary["stages_reached"] == ["initial"]
    assert summary["final_stage"] == "initial"
    assert summary["stage_errors"] == {}
    assert summary["degraded"] is False
    assert summary["postcondition_is_weak"] is False
    assert summary["used_fallback"] is False


def test_repair_ladder_records_stages_and_errors() -> None:
    summary = summarize_extraction(
        _extraction(
            trace_stages=("initial", "repair", "safe_repair"),
            errors_per_stage={
                "initial": ["postcondition uses python and/or/not"],
                "repair": ["postcondition uses infix And/Or"],
            },
            degraded=True,
            degraded_reason="recovered_safe_subset",
        )
    )
    assert summary["stages_reached"] == ["initial", "repair", "safe_repair"]
    # safe_repair succeeded -> final_stage is the last repair stage, not "sanitized"
    assert summary["final_stage"] == "safe_repair"
    assert summary["stage_errors"] == {"initial": 1, "repair": 1}
    assert summary["degraded"] is True
    assert summary["degraded_reason"] == "recovered_safe_subset"


def test_sanitization_collapse_marked_sanitized() -> None:
    summary = summarize_extraction(
        _extraction(
            postcondition="ret == ret",
            trace_stages=("initial", "repair", "safe_repair"),
            degraded=True,
            degraded_reason="sanitize_after_validation_failure",
        )
    )
    assert summary["final_stage"] == "sanitized"
    assert summary["degraded"] is True
    assert summary["postcondition_is_weak"] is True


def test_weak_postcondition_detection_handles_whitespace_variants() -> None:
    for form in ("ret == ret", "ret==ret", "True", "(ret == ret)"):
        summary = summarize_extraction(_extraction(postcondition=form))
        assert summary["postcondition_is_weak"] is True, form


def test_missing_trace_defaults_to_initial() -> None:
    # Fallback extractions are built directly from ExtractionResult and
    # do not carry an extraction_trace.
    summary = summarize_extraction(
        {
            "postcondition": "ret == If(a >= b, a, b)",
            "extraction_trace": None,
            "degraded": False,
            "used_fallback": True,
        }
    )
    assert summary["stages_reached"] == ["initial"]
    assert summary["final_stage"] == "initial"
    assert summary["used_fallback"] is True


def _case(
    *,
    spec: dict[str, object],
    code: dict[str, object],
    reason: str = "equivalent_no_mismatch",
    equivalent: bool = True,
    well_formedness: str = "ok",
) -> dict[str, object]:
    return {
        "spec_to_logic": {**spec, "extractor_health": summarize_extraction(spec)},
        "code_to_logic": {**code, "extractor_health": summarize_extraction(code)},
        "smt_checking": {
            "equivalent": equivalent,
            "reason": reason,
            "well_formedness": well_formedness,
        },
    }


def test_summarize_run_aggregates_extractor_and_verdict_distributions() -> None:
    cases = [
        _case(
            spec=_extraction(),
            code=_extraction(),
        ),
        _case(
            spec=_extraction(
                trace_stages=("initial", "repair"),
                degraded=True,
                degraded_reason="recovered_safe_subset",
            ),
            code=_extraction(),
            reason="case_post_spec",
            equivalent=False,
        ),
        _case(
            spec=_extraction(
                postcondition="ret == ret",
                trace_stages=("initial", "repair", "safe_repair"),
                degraded=True,
                degraded_reason="sanitize_after_validation_failure",
            ),
            code=_extraction(
                postcondition="ret == ret",
                trace_stages=("initial", "repair", "safe_repair"),
                degraded=True,
                degraded_reason="sanitize_after_validation_failure",
            ),
            reason="low_confidence_parse",
            equivalent=True,
        ),
        _case(
            spec=_extraction(),
            code=_extraction(),
            reason="solver_unknown",
            equivalent=False,
            well_formedness="solver_unknown_post",
        ),
    ]
    summary = summarize_run(cases)
    spec = summary["extractor_health"]["spec"]
    code = summary["extractor_health"]["code"]
    assert spec["total"] == 4
    assert code["total"] == 4
    assert spec["degraded_count"] == 2
    assert code["degraded_count"] == 1
    assert spec["weak_postcondition_count"] == 1
    assert code["weak_postcondition_count"] == 1
    assert spec["final_stage_counts"]["sanitized"] == 1
    assert spec["final_stage_counts"]["repair"] == 1
    assert summary["extractor_health"]["either_degraded_count"] == 2
    assert summary["extractor_health"]["both_degraded_count"] == 1
    assert summary["extractor_health"]["both_weak_postcondition_count"] == 1
    assert summary["verdict_distribution"] == {
        "equivalent_no_mismatch": 1,
        "case_post_spec": 1,
        "low_confidence_parse": 1,
        "solver_unknown": 1,
    }
    assert summary["well_formedness_distribution"]["ok"] == 3
    assert summary["well_formedness_distribution"]["solver_unknown_post"] == 1


def test_formula_parse_error_reasons_are_bucketed() -> None:
    cases = [
        _case(
            spec=_extraction(),
            code=_extraction(),
            reason=f"formula_parse_error: name {name!r} is not defined",
            equivalent=False,
        )
        for name in ("foo", "bar", "baz")
    ]
    summary = summarize_run(cases)
    assert summary["verdict_distribution"] == {"formula_parse_error": 3}


@pytest.mark.parametrize(
    "fixture",
    [
        "results/repo_scan_python-barcode_2026_04_14_14_50_50.json",
    ],
)
def test_summarize_run_on_existing_python_barcode_report(fixture: str) -> None:
    """Real-data sanity check: the empirical-snapshot numbers must be reproducible.

    The original review surfaced 47 low_confidence_parse cases out of 81 on
    the python-barcode run; the aggregator should rediscover that figure.
    """
    repo_root = Path(__file__).resolve().parents[1]
    fixture_path = repo_root / fixture
    if not fixture_path.exists():
        pytest.skip(f"fixture missing: {fixture}")
    data = json.loads(fixture_path.read_text())
    cases = data.get("results", [])
    summary = summarize_run(cases)
    assert summary["verdict_distribution"].get("low_confidence_parse") == 47
    assert summary["extractor_health"]["spec"]["total"] == 81
    assert summary["extractor_health"]["both_weak_postcondition_count"] == 47
