"""Sample candidate functions for benchmark/real/.

Runs Dualify's repo discovery over each downloaded package source, applies the
function-level filters from sampling-protocol.md, stratifies by return type, and
writes candidates.jsonl + selected.jsonl into ../cases/.

Run from the repo root:

    poetry run python m2-real-benchmark/tools/sample.py
"""

from __future__ import annotations

import ast
import dataclasses
import json
import re
from pathlib import Path

from dualify.discovery import discover_repo_cases

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # m2-real-benchmark/
SRC_DIR = ROOT / "packages" / "src"
CASES_DIR = ROOT / "cases"
CASES_DIR.mkdir(exist_ok=True)

CONTRACT_LIBS = ("icontract", "deal", "dpcontracts", "crosshair")
PLACEHOLDER_RE = re.compile(r"^Describe behavior of function '.*'\.$")
FMT_DIRECTIVE_RE = re.compile(r"^fmt:\s*(on|off)$", re.IGNORECASE)


def package_name(src_subdir: Path) -> str:
    # src/<name>-<version>/ -> <name>
    stem = src_subdir.name
    return re.sub(r"-\d.*$", "", stem)


def is_library_file(relative_file: str) -> bool:
    """Keep importable library modules; drop tests, scripts, build glue."""
    parts = [p.lower() for p in Path(relative_file).parts]
    name = parts[-1]
    if any(p in {"tests", "test", "testing", "bin", "scripts", "examples", "docs"} for p in parts):
        return False
    return not (name.startswith("test_") or name in {"conftest.py", "setup.py"})


def imports_contract_lib(case_source_file: Path) -> bool:
    try:
        tree = ast.parse(case_source_file.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return False
    for node in ast.walk(tree):
        roots: list[str] = []
        if isinstance(node, ast.Import):
            roots = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            roots = [(node.module or "").split(".")[0]]
        if any(root in CONTRACT_LIBS for root in roots):
            return True
    return False


def has_meaningful_informal_spec(spec: str) -> bool:
    spec = spec.strip()
    if not spec:
        return False
    if FMT_DIRECTIVE_RE.match(spec):
        return False
    if PLACEHOLDER_RE.match(spec):
        return False
    return len(spec.split()) >= 4


def short_name(qualname: str) -> str:
    return qualname.split(".")[-1]


def is_dunder(qualname: str) -> bool:
    name = short_name(qualname)
    return name.startswith("__") and name.endswith("__")


def is_test_or_noise(qualname: str) -> bool:
    name = short_name(qualname)
    return name.startswith("test_") or name.strip("_") == ""


def arity(case) -> int:
    # arg_types already excludes unannotated self/cls.
    return len(case.arg_types)


def returns_something(return_type: str) -> bool:
    return return_type.strip().lower() not in {"none", "noreturn"}


def stratum(return_type: str) -> str:
    rt = return_type.strip().lower()
    if rt == "bool":
        return "boolean"
    if rt in {"int", "float"} or rt in {"int | float", "float | int"}:
        return "numeric"
    if rt == "str":
        return "string"
    return "structured"


def main() -> None:
    all_cases = []
    for src_subdir in sorted(p for p in SRC_DIR.iterdir() if p.is_dir()):
        pkg = package_name(src_subdir)
        try:
            cases = discover_repo_cases(src_subdir)
        except Exception as exc:  # noqa: BLE001 - sampling tool, keep going
            print(f"  discovery failed for {pkg}: {exc}")
            continue
        kept = 0
        for case in cases:
            if not is_library_file(case.file):
                continue
            source_file = src_subdir / case.file
            if imports_contract_lib(source_file):
                continue
            if not has_meaningful_informal_spec(case.informal_spec):
                continue
            if is_dunder(case.qualname) or is_test_or_noise(case.qualname):
                continue
            if not (1 <= arity(case) <= 5):
                continue
            if not returns_something(case.return_type):
                continue
            record = dataclasses.asdict(case)
            record["package"] = pkg
            record["stratum"] = stratum(case.return_type)
            # Namespace the id by package to keep it globally unique.
            record["benchmark_id"] = f"{pkg}::{case.benchmark_id}"
            all_cases.append(record)
            kept += 1
        print(f"{pkg:16s} discovered={len(cases):4d} kept={kept}")

    # Deterministic order: package, then id.
    all_cases.sort(key=lambda r: (r["package"], r["benchmark_id"]))

    cand_path = CASES_DIR / "candidates.jsonl"
    with cand_path.open("w", encoding="utf-8") as fh:
        for rec in all_cases:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Stratified selection: 15 per stratum, redistribute shortfall to structured.
    # Within a stratum we pick round-robin across packages, so no single package
    # dominates the benchmark (external validity, review §5.3).
    target_per = {"boolean": 15, "numeric": 15, "string": 15, "structured": 15}
    by_stratum: dict[str, list] = {k: [] for k in target_per}
    for rec in all_cases:
        by_stratum[rec["stratum"]].append(rec)

    def round_robin(pool: list, quota: int) -> list:
        by_pkg: dict[str, list] = {}
        for rec in pool:
            by_pkg.setdefault(rec["package"], []).append(rec)
        # Stable package order; drain one per package per round.
        order = sorted(by_pkg)
        picked: list = []
        idx = {p: 0 for p in order}
        while len(picked) < quota and any(idx[p] < len(by_pkg[p]) for p in order):
            for p in order:
                if idx[p] < len(by_pkg[p]):
                    picked.append(by_pkg[p][idx[p]])
                    idx[p] += 1
                    if len(picked) >= quota:
                        break
        return picked

    selected: list = []
    shortfall = 0
    for strat in ("boolean", "numeric", "string"):
        take = round_robin(by_stratum[strat], target_per[strat])
        selected.extend(take)
        shortfall += target_per[strat] - len(take)
    selected.extend(round_robin(by_stratum["structured"], target_per["structured"] + shortfall))

    sel_path = CASES_DIR / "selected.jsonl"
    with sel_path.open("w", encoding="utf-8") as fh:
        for rec in selected:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print()
    print(f"candidates: {len(all_cases)}  -> {cand_path}")
    counts = {k: len(v) for k, v in by_stratum.items()}
    print(f"by stratum: {counts}")
    sel_counts: dict[str, int] = {}
    for rec in selected:
        sel_counts[rec["stratum"]] = sel_counts.get(rec["stratum"], 0) + 1
    print(f"selected: {len(selected)} {sel_counts} -> {sel_path}")


if __name__ == "__main__":
    main()
