# `benchmark/lifted_inconsistency/` — inconsistency-detection suite (RQ4)

This directory is a **forked benchmark** for the LLM-as-judge / no-SMT baseline
and its Dualify cross-check comparison. It is **not** the gold fidelity benchmark.

| Suite | Directory | Purpose | Size |
|---|---|---|---|
| Gold oracle | `benchmark/lifted/` | Human reference contracts | 40 YAML |
| Gold campaign input | `benchmark/lifted_auto_eval/` | RQ1–RQ3 (cross-check, gold fidelity, ablation) | 40 `.py` |
| **Inconsistency suite** | **`benchmark/lifted_inconsistency/`** | **RQ4 baseline only** | **40 `.py` (10 buggy / 30 correct)** |

## Fork relationship

- **30 correct** cases are copied from `benchmark/lifted_auto_eval/` (same stems).
- **10 buggy** cases are copied from the corpus incorrect pool with informal specs
  taken from the corpus or, when the corpus spec is junk (`fmt: on`), from the
  matching correct gold record.
- Ground-truth labels live in `manifest.json` (`buggy: true/false`), not in filenames.

Regenerate after editing the case lists in `scripts/build_inconsistency_benchmark.py`:

```bash
poetry run python scripts/build_inconsistency_benchmark.py
```

## Running RQ4 (record once, replay offline)

```bash
# 1) Dualify cross-check arm (records frozen p01/p02 transcripts)
PYTHONPATH=src poetry run python scripts/run_campaign.py \
  --provider openai --base-url http://HOST:8802 --api-key KEY \
  --model "Qwen/Qwen3-Coder-Next-FP8" \
  --benchmark lifted_inconsistency --runs 7 --label qwen_local

# 2) LLM-as-judge baseline (records its own judge transcripts)
PYTHONPATH=src poetry run python scripts/run_baseline_judge.py \
  --provider openai --base-url http://HOST:8802 --api-key KEY \
  --model "Qwen/Qwen3-Coder-Next-FP8" \
  --benchmark lifted_inconsistency --runs 7 --label qwen_local \
  --dualify-campaign results/campaigns/lifted_inconsistency__qwen_local

# 3) Offline replay (zero API calls)
PYTHONPATH=src poetry run python scripts/verify_reproducibility.py \
  results/campaigns/lifted_inconsistency__qwen_local
```

Results are stored under `results/campaigns/lifted_inconsistency__*` and
`results/baselines/lifted_inconsistency__*`, separate from the gold campaign
artifacts at `results/campaigns/lifted_auto_eval__*`.
