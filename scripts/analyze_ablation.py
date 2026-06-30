#!/usr/bin/env python3
"""Single-channel ablation: spec-only vs code-only vs full dual-channel.

Computed offline from an existing campaign's run reports (no new LLM calls), so
it reuses the exact extractions scored elsewhere. It contrasts three ways of
using Dualify's extractions:

* spec-only  : does the p01 (spec) contract match the gold reference?       (needs oracle)
* code-only  : does the p02 (code) contract match the gold reference?       (needs oracle)
* dual       : do p01 and p02 agree under Z3 cross-check?                   (NO oracle)

The point of bidirectional extraction is the last column: it flags spec-code
disagreements with no gold oracle at all. We also report, on the bug-injected
cases, which configuration surfaces the injected fault.

Usage:
    PYTHONPATH=src python scripts/analyze_ablation.py \
        results/campaigns/lifted_auto_eval__qwen_local
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dualify.aggregate import _stats  # noqa: E402
from dualify.io_utils import write_json  # noqa: E402


def _run_reports(campaign_dir: Path, benchmark: str) -> list[dict]:
    reports = []
    for run_dir in sorted(campaign_dir.glob("run_*")):
        found = list(run_dir.glob(f"{benchmark}_*.json"))
        if found:
            reports.append(json.loads(found[0].read_text()))
    return reports


def _is_buggy(case: dict) -> bool:
    return "incorrect" in str(case.get("file", "")) or "incorrect" in str(case.get("benchmark_id"))


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: analyze_ablation.py <campaign_dir>", file=sys.stderr)
        return 2
    campaign = Path(sys.argv[1]).resolve()
    meta = json.loads((campaign / "aggregate.json").read_text())
    benchmark = meta.get("benchmark", "lifted_auto_eval")
    reports = _run_reports(campaign, benchmark)
    if not reports:
        print("no run reports found", file=sys.stderr)
        return 2

    spec_only: list[float] = []
    code_only: list[float] = []
    dual: list[float] = []
    dual_flagged: list[float] = []  # non-equivalent cases found without oracle
    # Bug detection per channel, accumulated across runs.
    bug_detect = {"spec_only": 0, "code_only": 0, "dual": 0, "total_buggy": 0}

    for report in reports:
        results = report.get("results", [])
        s = c = d = flagged = 0
        for case in results:
            gold = case.get("gold_scoring") or {}
            spec = gold.get("spec", {}) if isinstance(gold, dict) else {}
            code = gold.get("code", {}) if isinstance(gold, dict) else {}
            equiv = bool(case.get("smt_checking", {}).get("equivalent"))
            if spec.get("contract_equivalent"):
                s += 1
            if code.get("contract_equivalent"):
                c += 1
            if equiv:
                d += 1
            else:
                flagged += 1
            if _is_buggy(case):
                bug_detect["total_buggy"] += 1
                # A channel "detects" the bug if its contract does NOT match gold,
                # or (dual) if the cross-check is non-equivalent.
                if spec and not spec.get("contract_equivalent"):
                    bug_detect["spec_only"] += 1
                if code and not code.get("contract_equivalent"):
                    bug_detect["code_only"] += 1
                if not equiv:
                    bug_detect["dual"] += 1
        spec_only.append(float(s))
        code_only.append(float(c))
        dual.append(float(d))
        dual_flagged.append(float(flagged))

    total = float(reports[0].get("summary", {}).get("total_cases", 0))
    out = {
        "campaign": str(campaign),
        "benchmark": benchmark,
        "n_runs": len(reports),
        "total_cases": total,
        "spec_only_matches_gold": _stats(spec_only),
        "code_only_matches_gold": _stats(code_only),
        "dual_cross_check_equivalent": _stats(dual),
        "dual_flagged_without_oracle": _stats(dual_flagged),
        "bug_injected_detection": bug_detect,
        "note": (
            "spec-only and code-only require the gold oracle to find anything; "
            "the dual cross-check flags spec-code disagreements with no oracle "
            "(dual_flagged_without_oracle)."
        ),
    }
    write_json(campaign / "ablation.json", out)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
