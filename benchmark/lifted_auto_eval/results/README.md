# lifted_auto_eval results

Evaluation outputs comparing Dualify extraction to gold contracts in `benchmark/lifted/`.

## Folders

- `qwen3_coder_next_fp8_2026_06_16/` — initial 3-run baseline (before pipeline fixes)
- `improved_2026_06_16/` — after gold fixes + Dualify parser/extraction/p03 improvements

Each subfolder contains raw JSON reports, `cases.csv`, `summary.json`, and `README.md`.
The `improved_2026_06_16/` folder also has `IMPROVEMENTS.md` documenting what changed.
