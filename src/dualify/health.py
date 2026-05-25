"""Per-case and per-run extractor / SMT health summarization.

Existing run reports record the full ``extraction_trace`` of every
case but only surface raw fallback counts at the run level. The
helpers in this module distill that trace into per-case and per-run
summaries that the JSON report can carry as first-class fields, so
extractor failure modes are visible without trace introspection.

Per-case summary (``summarize_extraction``):

    {
      "stages_reached": ["initial", "repair", "safe_repair"],
      "final_stage": "safe_repair",
      "stage_errors": {"initial": 2, "repair": 1},
      "degraded": True,
      "degraded_reason": "recovered_safe_subset",
      "postcondition_is_weak": False,
      "used_fallback": False,
    }

Per-run summary (``summarize_run``) reports extractor distributions
on each side (spec/code), the joint "either / both" rollups, the
distribution of ``smt_checking.reason``, and the distribution of
``smt_checking.well_formedness``.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

WEAK_POSTCONDITION_FORMS = {
    "ret==ret",
    "ret == ret",
    "True",
    "(True)",
    "(ret==ret)",
    "(ret == ret)",
}


_REPAIR_STAGES = ("initial", "repair", "safe_repair")


_WEAK_FORMS_NORMALIZED = {form.replace(" ", "") for form in WEAK_POSTCONDITION_FORMS}


def _is_weak_postcondition(postcondition: str) -> bool:
    return postcondition.replace(" ", "") in _WEAK_FORMS_NORMALIZED


def summarize_extraction(extraction: dict[str, Any]) -> dict[str, Any]:
    """Distill an ExtractionResult (as a dict) into a one-shot health record.

    Accepts the dict form already emitted by the runner (``asdict``
    of ``ExtractionResult``, with an optional ``used_fallback`` key).
    """
    trace = extraction.get("extraction_trace") or {}
    if not isinstance(trace, dict):
        trace = {}

    stages_reached: list[str] = []
    stage_errors: dict[str, int] = {}
    for stage in _REPAIR_STAGES:
        stage_payload = trace.get(stage)
        if not isinstance(stage_payload, dict):
            continue
        stages_reached.append(stage)
        errors = stage_payload.get("errors")
        if isinstance(errors, list) and errors:
            stage_errors[stage] = len(errors)

    if not stages_reached:
        # Trace wasn't recorded -- this happens for fallback extractions
        # built directly from a hand-written ExtractionResult, and also
        # for older runs predating the trace work.
        stages_reached = ["initial"]

    degraded = bool(extraction.get("degraded", False))
    degraded_reason = extraction.get("degraded_reason", "") or ""
    if not isinstance(degraded_reason, str):
        degraded_reason = ""

    if degraded and degraded_reason == "sanitize_after_validation_failure":
        final_stage = "sanitized"
    else:
        final_stage = stages_reached[-1]

    postcondition = extraction.get("postcondition", "")
    if not isinstance(postcondition, str):
        postcondition = ""

    return {
        "stages_reached": stages_reached,
        "final_stage": final_stage,
        "stage_errors": stage_errors,
        "degraded": degraded,
        "degraded_reason": degraded_reason,
        "postcondition_is_weak": _is_weak_postcondition(postcondition),
        "used_fallback": bool(extraction.get("used_fallback", False)),
    }


def _side_distribution(case_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    final_stages: Counter[str] = Counter()
    for summary in case_summaries:
        final_stages[summary["final_stage"]] += 1
    return {
        "total": len(case_summaries),
        "final_stage_counts": dict(final_stages),
        "degraded_count": sum(1 for s in case_summaries if s["degraded"]),
        "weak_postcondition_count": sum(1 for s in case_summaries if s["postcondition_is_weak"]),
        "used_fallback_count": sum(1 for s in case_summaries if s["used_fallback"]),
    }


def summarize_run(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-case results into the run-level health summary.

    Each entry of ``case_results`` is expected to follow the shape the
    runner emits: ``spec_to_logic``, ``code_to_logic``, ``smt_checking``
    each carrying the per-case summary that ``summarize_extraction``
    consumes.
    """
    spec_summaries: list[dict[str, Any]] = []
    code_summaries: list[dict[str, Any]] = []
    verdict_counts: Counter[str] = Counter()
    well_formedness_counts: Counter[str] = Counter()

    for case in case_results:
        spec_payload = case.get("spec_to_logic")
        if isinstance(spec_payload, dict):
            spec_health = spec_payload.get("extractor_health") or summarize_extraction(spec_payload)
            spec_summaries.append(spec_health)
        code_payload = case.get("code_to_logic")
        if isinstance(code_payload, dict):
            code_health = code_payload.get("extractor_health") or summarize_extraction(code_payload)
            code_summaries.append(code_health)
        smt_payload = case.get("smt_checking")
        if isinstance(smt_payload, dict):
            reason = smt_payload.get("reason")
            if isinstance(reason, str):
                # Collapse parse errors with arbitrary message tails into a
                # single bucket so the distribution stays readable.
                if reason.startswith("formula_parse_error"):
                    head = reason.split(":", 1)[0]
                else:
                    head = reason
                verdict_counts[head] += 1
            wf = smt_payload.get("well_formedness", "ok")
            well_formedness_counts[wf if isinstance(wf, str) else "ok"] += 1

    either_degraded = sum(
        1
        for spec, code in zip(spec_summaries, code_summaries, strict=False)
        if spec["degraded"] or code["degraded"]
    )
    both_degraded = sum(
        1
        for spec, code in zip(spec_summaries, code_summaries, strict=False)
        if spec["degraded"] and code["degraded"]
    )
    either_weak = sum(
        1
        for spec, code in zip(spec_summaries, code_summaries, strict=False)
        if spec["postcondition_is_weak"] or code["postcondition_is_weak"]
    )
    both_weak = sum(
        1
        for spec, code in zip(spec_summaries, code_summaries, strict=False)
        if spec["postcondition_is_weak"] and code["postcondition_is_weak"]
    )

    return {
        "extractor_health": {
            "spec": _side_distribution(spec_summaries),
            "code": _side_distribution(code_summaries),
            "either_degraded_count": either_degraded,
            "both_degraded_count": both_degraded,
            "either_weak_postcondition_count": either_weak,
            "both_weak_postcondition_count": both_weak,
        },
        "verdict_distribution": dict(verdict_counts),
        "well_formedness_distribution": dict(well_formedness_counts),
    }
