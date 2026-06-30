# Expert review bundle — gold benchmark evaluation

Frozen copies of artifacts cited in the paper evaluation (§5–6).

## Layout

| Path | Role |
|------|------|
| `paper-run/` | **Primary run** for Table 1 and Figures cross-check / gold-fidelity |
| `stability-runs/` | Three pre-fix replications for RQ3 (cross-check only) |
| `gold-reference/` | 40 human-confirmed gold YAMLs (`benchmark/lifted/`) |
| `inputs/` | 40 Python snippets used for end-to-end eval |
| `paper-figures/` | PDF figures generated from the primary run |

## Primary run

- **File:** `paper-run/lifted_auto_eval_2026_06_17_07_45_58.json`
- **Model:** Qwen/Qwen3-Coder-Next-FP8
- **Cases:** 40 total; gold scoring on 36 in-fragment
- **Paper metrics:** cross-check 10/40 (25%); spec pre 14/36, post 3/36; code pre 12/36, post 4/36

Per-case fields to inspect: `spec_to_logic`, `code_to_logic`, `smt_checking`, `gold_scoring`.

## Stability runs (RQ3)

| File | Cross-check equivalent |
|------|------------------------|
| `lifted_auto_eval_2026_06_16_13_36_39.json` | 7/40 |
| `lifted_auto_eval_2026_06_16_13_14_17.json` | 10/40 |
| `lifted_auto_eval_2026_06_16_13_42_00.json` | 11/40 |

These runs predate gold scoring in the JSON summary; use `smt_checking.equivalent` per case.

## Regenerate figures (optional)

Figures are generated from the companion paper submodule under `conferences/` (see that repo’s `scripts/generate_figures.py`).
