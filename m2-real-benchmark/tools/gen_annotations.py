"""Generate per-case annotation cards under ../annotations/.

Each YAML card embeds the selected case (signature, informal spec, source) and
the hand-drafted gold reference, then leaves the p01 block and the two annotator
columns empty. The reference is the scoring key; once p01 has been run against a
hosted model (see sampling-protocol.md §5), `tools/fill_p01.py` drops its clauses
into the p01 block and the annotators label them relevant/wrong/irrelevant
against the reference.

    poetry run python m2-real-benchmark/tools/gen_annotations.py
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
ANN_DIR.mkdir(exist_ok=True)


def flatten_id(bid: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", bid).strip("_")


def main() -> None:
    selected = {
        json.loads(line)["benchmark_id"]: json.loads(line)
        for line in (CASES_DIR / "selected.jsonl").open()
    }
    reference = {
        json.loads(line)["benchmark_id"]: json.loads(line)
        for line in (CASES_DIR / "reference.jsonl").open()
    }

    written = 0
    for bid, case in selected.items():
        ref = reference.get(bid, {})
        doc = {
            "benchmark_id": bid,
            "package": case["package"],
            "stratum": case["stratum"],
            "signature": case["signature"],
            "informal_spec": case["informal_spec"],
            "function_source": case["function_source"],
            # --- gold reference (hand-drafted, inference-free scoring key) ---
            "reference": {
                "behavior_summary": ref.get("behavior_summary"),
                "fragment_fit": ref.get("fragment_fit"),
                "reference_pre": ref.get("reference_pre", []),
                "reference_post": ref.get("reference_post"),
                "profile": ref.get("profile"),
                "difficulty": ref.get("difficulty"),
                "notes": ref.get("notes"),
            },
            # --- p01 output: filled by tools/fill_p01.py after the hosted run ---
            "p01": {
                "status": "pending_hosted_run",
                "domain_constraints": [],
                "postcondition": None,
                "confidence": None,
                "degraded": None,
            },
            # --- Polikarpova labels on p01 clauses, against the reference above ---
            "annotations": {
                "annotator_1": {"postcondition": None, "domain_constraints": [], "note": ""},
                "annotator_2": {"postcondition": None, "domain_constraints": [], "note": ""},
            },
            "adjudicated": {"postcondition": None, "domain_constraints": []},
        }
        out = ANN_DIR / f"{flatten_id(bid)}.yaml"
        out.write_text(
            yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100),
            encoding="utf-8",
        )
        written += 1
    print(f"wrote {written} annotation cards to {ANN_DIR}")


if __name__ == "__main__":
    main()
