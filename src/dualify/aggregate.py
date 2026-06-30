"""Aggregate several Dualify run reports into mean/spread statistics.

The paper reports averages and spread across repeated runs rather than a single
best run. This module turns a list of run-report dicts (as written under
``results/``) into per-metric ``{mean, median, std, min, max, n, values}``
records for the cross-check and gold-fidelity metrics.
"""

from __future__ import annotations

import statistics
from typing import Any


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "mean": 0.0,
            "median": 0.0,
            "std": 0.0,
            "min": 0.0,
            "max": 0.0,
            "n": 0,
            "values": [],
        }
    return {
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "std": statistics.pstdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
        "n": len(values),
        "values": list(values),
    }


_CROSS_CHECK_FIELDS = (
    "equivalent_cases",
    "genuine_equivalent_cases",
    "low_confidence_cases",
    "solver_unknown_cases",
    "parse_error_cases",
    "non_equivalent_cases",
)

_GOLD_FIELDS = (
    "scorable_cases",
    "spec_pre_exact",
    "spec_post_exact",
    "spec_contract_equivalent",
    "code_pre_exact",
    "code_post_exact",
    "code_contract_equivalent",
    "spec_parse_errors",
    "code_parse_errors",
)


def _collect(
    reports: list[dict[str, Any]],
    section_path: list[str],
    fields: tuple[str, ...],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field in fields:
        values: list[float] = []
        for report in reports:
            node: Any = report.get("summary", {})
            for key in section_path:
                node = node.get(key, {}) if isinstance(node, dict) else {}
            if isinstance(node, dict) and isinstance(node.get(field), (int, float)):
                values.append(float(node[field]))
        out[field] = _stats(values)
    return out


def aggregate_runs(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Return aggregate statistics across *reports* for the headline metrics."""
    total = [
        float(r.get("summary", {}).get("total_cases", 0))
        for r in reports
        if isinstance(r.get("summary"), dict)
    ]
    return {
        "n_runs": len(reports),
        "total_cases": _stats(total),
        "cross_check": _collect(reports, ["cross_check"], _CROSS_CHECK_FIELDS),
        "gold_scoring": _collect(reports, ["gold_scoring"], _GOLD_FIELDS),
        "run_ids": [r.get("run_id") for r in reports],
        "models": sorted({str(r.get("model")) for r in reports if r.get("model")}),
    }


def stable_cases(
    reports: list[dict[str, Any]],
    predicate_key: str = "equivalent",
) -> dict[str, Any]:
    """Stability across runs: how many cases are always/never/sometimes True.

    ``predicate_key`` selects the boolean field in each case's ``smt_checking``
    (default the cross-check ``equivalent`` verdict).
    """
    per_case: dict[str, list[bool]] = {}
    for report in reports:
        for case in report.get("results", []):
            if not isinstance(case, dict):
                continue
            # Composite key: bare benchmark_id collides across variants
            # (double/swap/...); pairing with the source file keeps all 40 distinct.
            key = f"{case.get('file', '')}::{case.get('benchmark_id', '')}"
            smt = case.get("smt_checking", {})
            val = bool(smt.get(predicate_key)) if isinstance(smt, dict) else False
            per_case.setdefault(key, []).append(val)

    always = sum(1 for vals in per_case.values() if vals and all(vals))
    never = sum(1 for vals in per_case.values() if vals and not any(vals))
    sometimes = sum(1 for vals in per_case.values() if len(set(vals)) > 1)
    return {
        "n_runs": len(reports),
        "total_cases": len(per_case),
        "always": always,
        "never": never,
        "unstable": sometimes,
    }
