"""Merge the per-batch reference drafts into cases/reference.jsonl.

Cross-checks ids against selected.jsonl, and runs every in/near reference
formula through Dualify's own normalize_formula + validate_formula so we know
which hand-drafted contracts are actually inside the fragment.

    poetry run python m2-real-benchmark/tools/merge_reference.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from dualify.formula_parser import normalize_formula, validate_formula

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CASES_DIR = ROOT / "cases"


def allowed_names_for(case: dict) -> set[str]:
    names = set(case["arg_types"].keys()) | {"ret"}
    # self.x attributes used in references normalise to self_x.
    blob = " ".join([case.get("function_source", ""), case.get("extra_context", "")])
    names |= {f"self_{m}" for m in re.findall(r"\bself\.([A-Za-z_]\w*)\b", blob)}
    # references also mention other_x for binary version methods
    names |= {f"other_{m}" for m in re.findall(r"\bother\.([A-Za-z_]\w*)\b", blob)}
    return names


def check_formula(expr: str, allowed: set[str]) -> list[str]:
    try:
        normalized = normalize_formula(expr)
    except Exception as exc:  # noqa: BLE001
        return [f"normalize_error: {exc}"]
    # validate_formula needs to also accept the self_/other_ symbols and ints.
    return validate_formula(normalized, allowed)


def main() -> None:
    selected = {
        json.loads(line)["benchmark_id"]: json.loads(line)
        for line in (CASES_DIR / "selected.jsonl").open()
    }
    refs: list[dict] = []
    for i in range(4):
        refs.extend(json.loads((CASES_DIR / f"_ref_batch_{i}.json").read_text()))

    by_id = {r["benchmark_id"]: r for r in refs}
    missing = set(selected) - set(by_id)
    extra = set(by_id) - set(selected)
    if missing:
        print(f"!! references MISSING for {len(missing)} cases:")
        for m in sorted(missing):
            print("   ", m)
    if extra:
        print(f"!! references with UNKNOWN id ({len(extra)}):")
        for e in sorted(extra):
            print("   ", e)

    # Emit in selected order, attach fragment-validation outcome.
    out_path = CASES_DIR / "reference.jsonl"
    fit_counts = {"in": 0, "near": 0, "out": 0}
    parse_ok = parse_bad = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for bid, case in selected.items():
            r = by_id.get(bid)
            if r is None:
                continue
            fit_counts[r["fragment_fit"]] = fit_counts.get(r["fragment_fit"], 0) + 1
            allowed = allowed_names_for(case)
            validation = {}
            if r["fragment_fit"] in {"in", "near"}:
                errs_pre = {p: check_formula(p, allowed) for p in (r.get("reference_pre") or [])}
                post = r.get("reference_post")
                errs_post = check_formula(post, allowed) if post else ["(null)"]
                in_fragment = (
                    (post is not None) and (not errs_post) and all(not v for v in errs_pre.values())
                )
                validation = {
                    "post_errors": errs_post,
                    "pre_errors": {k: v for k, v in errs_pre.items() if v},
                    "parser_in_fragment": in_fragment,
                }
                if in_fragment:
                    parse_ok += 1
                else:
                    parse_bad += 1
            r2 = dict(r)
            r2["package"] = case["package"]
            r2["stratum"] = case["stratum"]
            r2["validation"] = validation
            fh.write(json.dumps(r2, ensure_ascii=False) + "\n")

    print(f"\nwrote {out_path}")
    print(f"fragment_fit: {fit_counts}")
    print(f"in/near refs that pass the Dualify parser: {parse_ok}; fail: {parse_bad}")


if __name__ == "__main__":
    main()
