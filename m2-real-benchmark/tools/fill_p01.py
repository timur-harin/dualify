"""Merge hosted-model p01 output into the annotation cards.

Run AFTER tools/run_p01.py has produced cases/p01_results.jsonl against a
properly-sized hosted model. For each card it fills the `p01` block and sizes
the two annotators' `domain_constraints` label lists to the number of p01
clauses (one label slot per clause, plus the postcondition slot).

    poetry run python m2-real-benchmark/tools/fill_p01.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CASES_DIR = ROOT / "cases"
ANN_DIR = ROOT / "annotations"


def flatten_id(bid: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", bid).strip("_")


def main() -> None:
    p01_path = CASES_DIR / "p01_results.jsonl"
    if not p01_path.exists():
        raise SystemExit(
            "cases/p01_results.jsonl not found — run tools/run_p01.py against a "
            "hosted model first (see sampling-protocol.md §5)."
        )
    p01 = {json.loads(line)["benchmark_id"]: json.loads(line) for line in p01_path.open()}

    updated = 0
    for card_path in sorted(ANN_DIR.glob("*.yaml")):
        doc = yaml.safe_load(card_path.read_text(encoding="utf-8"))
        res = p01.get(doc["benchmark_id"])
        if res is None:
            continue
        constraints = res.get("domain_constraints", [])
        doc["p01"] = {
            "status": "filled",
            "model": res.get("model"),
            "domain_constraints": constraints,
            "postcondition": res.get("postcondition"),
            "confidence": res.get("confidence"),
            "degraded": res.get("degraded"),
            "degraded_reason": res.get("degraded_reason", ""),
        }
        for who in ("annotator_1", "annotator_2"):
            doc["annotations"][who]["domain_constraints"] = [None] * len(constraints)
        doc["adjudicated"]["domain_constraints"] = [None] * len(constraints)
        card_path.write_text(
            yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100),
            encoding="utf-8",
        )
        updated += 1
    print(f"filled p01 into {updated} cards")


if __name__ == "__main__":
    main()
