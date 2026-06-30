# Agent end-to-end run (operator-as-orchestrator)

Re-run of the anonymized OSS input-validation case study with the improved Dualify pipeline
(type-check gate, honest cross-check metric, port `:8802`,
`Qwen/Qwen3-Coder-Next-FP8`). The agent (this run) acts as the operator: it
reads each Dualify comparison report, selects an action from the closed menu,
and records the decision.

## Pipeline

```bash
PYTHONPATH=src python case_studies/pathvalidate/run_operator_loop.py \
  --base-url http://10.100.30.241:8802 --api-key API_KEY \
  --model Qwen/Qwen3-Coder-Next-FP8 --fresh-transcript --run-p05
```

Artifacts: `transcript.jsonl` (frozen LLM calls), `operator_log.jsonl`
(per-function decision + rationale), `baseline.json` (fingerprints).

## Operator adjudication (6 in-scope functions)

The SMT cross-check on these documentation-heavy wrapper functions mostly yields
`low_confidence_parse` / `case_post_code` (wrappers delegate to validators, so
the code channel under-constrains in the fragment). The operator routes these to
`investigate_instrumentation` and performs a manual doc/code review, which is the
intended workflow when extraction is weak but a mismatch hypothesis is plausible.
Two true documentation-drift findings were confirmed:

1. `is_valid_filename` Args omitted `min_len`/`max_len`/... and, critically,
   `max_len=None` selects the platform limit, not `validate_filename`'s `255`.
2. `sanitize_filename` / `sanitize_filepath` documented `Raises: ValueError`,
   but the public API raises `ValidationError`.

## Result: anonymized patch artifact

Fixes + regression tests are packaged as a pull-request-style patch artifact.
The de-anonymized fork/PR URL is intentionally omitted from the double-blind
artifact and can be released after review:

- Patch: `patches/pathvalidate-doc-alignment.patch`
- Tests: `test/test_dualify_case_study.py` (2 passed)

## Honest limitation

The SMT cross-check alone did not mechanically prove these mismatches: the
wrapper functions degrade to low-confidence extractions, and the operator's
manual review (guided by Dualify's report + counterexamples) closed the gap.
This is the operator-as-orchestrator pattern, not fully autonomous repair.
