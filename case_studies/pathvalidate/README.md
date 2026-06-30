# Anonymized input-validation × Dualify — case study artifact

External OSS pilot for operator-as-orchestrator (companion paper case-study section).  
The repository name, upstream URL, and fork URL are withheld in the double-blind
artifact. The de-anonymized release can restore them after review.

## Layout

| Path | Description |
|------|-------------|
| `SCOPE.md` | Six public API functions in scope |
| `COMMIT_SHA` | Pinned upstream commit |
| `run_operator_loop.py` | Interactive-style loop without stdin; LLM-as-judge action policy |
| `transcript.jsonl` | Recorded LLM calls (Qwen3-Coder-Next-FP8 @ vLLM) |
| `baseline.json` | Full Dualify fingerprints for 6 functions |
| `operator_log.jsonl` | Per-function operator decision + rationale |
| `operator_run.log` | Console capture |
| `triage.csv` | TP / FP / UN adjudication |
| `patches/pathvalidate-doc-alignment.patch` | Doc + regression tests applied to the anonymized OSS checkout |
| `NARRATIVE.md` | Deep-dive for paper box |

## Reproduce baseline scan

```bash
cd /path/to/dualify
git clone <anonymized-upstream-url> repos/oss-input-validation
cd repos/oss-input-validation && git checkout <pinned-commit>

poetry run python case_studies/pathvalidate/run_operator_loop.py \
  --base-url http://10.100.30.241:8801 \
  --api-key API_KEY \
  --model Qwen/Qwen3-Coder-Next-FP8 \
  --fresh-transcript
```

## Apply documented fixes (local checkout)

```bash
cd repos/oss-input-validation
git apply ../../case_studies/pathvalidate/patches/pathvalidate-doc-alignment.patch
PYTHONPATH=. poetry run pytest test/test_dualify_case_study.py -q
```

## Baseline summary (6 functions)

| Metric | Value |
|--------|-------|
| Z3 equivalent | 2 / 6 (`validate_filename`, `sanitize_filename`) |
| `low_confidence_parse` | 2 |
| `formula_parse_error` | 2 |
| `case_post_code` | 2 |
| Manual TP (doc fixes) | 2 |
| Regression tests added | 2 |

## Operator mode

Uses the same comparison reports as `dualify-run` (interactive CLI) but replaces stdin with a **deterministic judge policy** in `run_operator_loop.py` (`_judge_select_action`). Decisions are logged for audit.

True interactive CLI (human at terminal):

```bash
poetry run dualify-run \
  --provider openai --base-url http://10.100.30.241:8801 --api-key API_KEY \
  --model Qwen/Qwen3-Coder-Next-FP8 \
  --repo-path ./repos/oss-input-validation \
  --target-regex '_filename.py::validate_filename'
```
