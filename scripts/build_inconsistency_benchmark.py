#!/usr/bin/env python3
"""Build ``benchmark/lifted_inconsistency/`` — a forked suite for RQ4 only.

This benchmark is intentionally separate from ``benchmark/lifted/`` (gold oracle)
and ``benchmark/lifted_auto_eval/`` (RQ1–RQ3 campaign input). It reuses curated
informal specs and correct implementations from the gold fork where possible, and
pulls known-buggy implementations from the corpus incorrect pool.

Output:
  - ``benchmark/lifted_inconsistency/*.py``  (40 runnable snippets)
  - ``benchmark/lifted_inconsistency/manifest.json``  (ground-truth labels)

Regenerate after editing ``CASES`` below:

    PYTHONPATH=src poetry run python scripts/build_inconsistency_benchmark.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLD_EVAL = ROOT / "benchmark" / "lifted_auto_eval"
GOLD_YAML = ROOT / "benchmark" / "lifted"
CORPUS = ROOT / "benchmark/dataset/runs/2026_05_05_08_59_47/clean/canonical_records.jsonl"
OUT = ROOT / "benchmark" / "lifted_inconsistency"

# 10 buggy (corpus incorrect) + 30 correct (forked from gold eval).
BUGGY_BIDS = [
    "python_by_contract::incorrect_from_recorded::aoc2020::day_13_shuttle_search::wrong_mod.py::next_departure",
    "python_by_contract::incorrect_from_recorded::aoc2020::day_24_lobby_layout::missed_to_handle_empty_directions_in_plan.py::count_flips",
    "python_by_contract::incorrect_from_recorded::aoc2020::day_1_report_repair::pair_cannot_be_the_same_number.py::find_pair_with_sum",
    "python_by_contract::incorrect_from_recorded::aoc2020::day_24_lobby_layout::stringify_directions_missed_to_handle_empty_directions.py::parse_line",
    "python_by_contract::incorrect_from_recorded::aoc2020::day_14_docking_data::one_off_mistake.py::parse_mask",
    "python_by_contract::incorrect_from_recorded::ethz_eprog_2019::exercise_04::problem_02::tolerance_needs_to_match_machine_precision.py::approximate_sqrt",
    "python_by_contract::incorrect_from_recorded::ethz_eprog_2019::exercise_08::problem_05::got_half_grid_size_wrong.py::simulate",
    "python_by_contract::incorrect_from_recorded::aoc2020::day_13_shuttle_search::divide_by_zero_bug.py::next_departure",
    "python_by_contract::incorrect_from_recorded::ethz_eprog_2019::exercise_05::problem_03::binary_search_wrong.py::bin_index",
    "python_by_contract::incorrect_from_recorded::ethz_eprog_2019::exercise_12::problem_03::forgot_to_check_for_nan_when_comparing_interpret_and_compile_and_execute.py::compile_and_execute",
]

CORRECT_STEMS = [
    "crosshair_examples_PEP316_correct_code_arith.py_double",
    "crosshair_examples_PEP316_correct_code_arith.py_perimiter_length",
    "crosshair_examples_PEP316_correct_code_arith.py_swap",
    "crosshair_examples_PEP316_correct_code_chess.py_ChessPiece_can_move_to",
    "crosshair_examples_PEP316_correct_code_numpy_examples.py_unit_normalize",
    "crosshair_examples_PEP316_correct_code_showcase.py_even_fibb",
    "crosshair_examples_deal_correct_code_average.py_average",
    "crosshair_examples_icontract_correct_code_arith.py_double",
    "crosshair_examples_icontract_correct_code_arith.py_perimiter_length",
    "crosshair_examples_PEP316_correct_code_arith.py__assert_double_swap_does_nothing",
    "crosshair_examples_icontract_correct_code_arith.py_swap",
    "crosshair_examples_icontract_correct_code_showcase.py_compute_grade",
    "crosshair_examples_icontract_correct_code_showcase.py_csv_first_column",
    "crosshair_examples_icontract_correct_code_showcase.py_duplicate_list",
    "crosshair_examples_icontract_correct_code_showcase.py_even_fibb",
    "crosshair_examples_icontract_correct_code_showcase.py_zip_exact",
    "crosshair_examples_icontract_correct_code_showcase.py_zipped_pairs",
    "python_by_contract_correct_aoc2020_day_11_seating_system.py_list_neighbourhood",
    "python_by_contract_correct_aoc2020_day_13_shuttle_search.py_find_departure",
    "python_by_contract_correct_aoc2020_day_13_shuttle_search.py_next_departure",
    "python_by_contract_correct_aoc2020_day_17_conway_cubes.py_count_active",
    "python_by_contract_correct_aoc2020_day_18_operation_order.py_extract_expression",
    "python_by_contract_correct_aoc2020_day_1_report_repair.py_find_pair_with_sum",
    "python_by_contract_correct_aoc2020_day_20_jurassic_jigsaw.py_reverse_side",
    "python_by_contract_correct_aoc2020_day_22_crab_combat.py_compute_score",
    "python_by_contract_correct_aoc2020_day_25_combo_breaker.py_transform",
    "python_by_contract_correct_aoc2020_day_2_password_philosophy.py_verify",
    "python_by_contract_correct_aoc2020_day_3_toboggan_trajectory.py_count_trees",
    "python_by_contract_correct_aoc2020_day_5_binary_boarding.py_determine_column",
    "python_by_contract_correct_ethz_eprog_2019_exercise_03_problem_01.py_compute",
]


def _safe_stem(benchmark_id: str) -> str:
    return benchmark_id.replace("::", "_").replace("/", "_")


def _load_corpus() -> dict[str, dict]:
    records: dict[str, dict] = {}
    for line in CORPUS.read_text().splitlines():
        record = json.loads(line)
        records[record["benchmark_id"]] = record
    return records


def _load_gold_spec(stem: str) -> str:
    path = GOLD_YAML / f"{stem}.yaml"
    if not path.exists():
        return ""
    import yaml  # type: ignore[import-untyped]

    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        return ""
    return str(data.get("informal_spec") or data.get("informal_spec_raw") or "").strip()


def _spec_for_buggy(bid: str, corpus: dict[str, dict]) -> str:
    record = corpus[bid]
    spec = str(record.get("informal_spec") or record.get("informal_spec_raw") or "").strip()
    if spec and spec.lower() != "fmt: on":
        return spec
    # Fall back to the matching correct gold record when corpus spec is junk.
    qualname = record.get("qualname", "")
    for path in GOLD_YAML.glob("*.yaml"):
        if "incorrect" in path.name:
            continue
        import yaml  # type: ignore[import-untyped]

        data = yaml.safe_load(path.read_text())
        if isinstance(data, dict) and data.get("qualname") == qualname:
            alt = str(data.get("informal_spec") or "").strip()
            if alt:
                return alt
    return spec or qualname


def _render_py(spec_lines: str, function_source: str) -> str:
    spec_block = "\n".join(f"# {line}" if line else "#" for line in spec_lines.splitlines())
    body = function_source.strip("\n")
    if not body.endswith("\n"):
        body += "\n"
    return f"{spec_block}\n{body}"


def _write_buggy_py(bid: str, corpus: dict[str, dict]) -> tuple[str, str]:
    record = corpus[bid]
    stem = _safe_stem(bid)
    spec = _spec_for_buggy(bid, corpus)
    source = str(record.get("function_source") or "")
    if not source.strip():
        raise ValueError(f"empty function_source for {bid}")
    OUT.joinpath(f"{stem}.py").write_text(_render_py(spec, source))
    return stem, record.get("qualname", "")


def main() -> None:
    corpus = _load_corpus()
    OUT.mkdir(parents=True, exist_ok=True)

    # Remove stale generated files.
    for old in OUT.glob("*.py"):
        old.unlink()

    cases: list[dict] = []

    for bid in BUGGY_BIDS:
        if bid not in corpus:
            raise KeyError(f"missing corpus record: {bid}")
        stem, qualname = _write_buggy_py(bid, corpus)
        cases.append(
            {
                "stem": stem,
                "qualname": qualname,
                "benchmark_id": bid,
                "buggy": True,
                "forked_from": "corpus_incorrect",
            }
        )

    for stem in CORRECT_STEMS:
        src = GOLD_EVAL / f"{stem}.py"
        if not src.exists():
            raise FileNotFoundError(src)
        dst = OUT / f"{stem}.py"
        dst.write_text(src.read_text())
        import yaml  # type: ignore[import-untyped]

        gold_path = GOLD_YAML / f"{stem}.yaml"
        gold = yaml.safe_load(gold_path.read_text()) if gold_path.exists() else {}
        bid = str(gold.get("benchmark_id", stem)) if isinstance(gold, dict) else stem
        qualname = (
            str(gold.get("qualname", stem.split("_")[-1])) if isinstance(gold, dict) else stem
        )
        cases.append(
            {
                "stem": stem,
                "qualname": qualname,
                "benchmark_id": bid,
                "buggy": False,
                "forked_from": "lifted_auto_eval",
                "gold_stem": stem,
            }
        )

    manifest = {
        "benchmark": "lifted_inconsistency",
        "description": "Forked inconsistency-detection suite for RQ4 (10 buggy / 30 correct).",
        "parent_gold_benchmark": "benchmark/lifted",
        "parent_gold_eval": "benchmark/lifted_auto_eval",
        "n_cases": len(cases),
        "n_buggy": sum(1 for c in cases if c["buggy"]),
        "n_correct": sum(1 for c in cases if not c["buggy"]),
        "cases": sorted(cases, key=lambda c: c["stem"]),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Wrote {len(cases)} cases to {OUT}")
    print(f"  buggy={manifest['n_buggy']} correct={manifest['n_correct']}")


if __name__ == "__main__":
    main()
