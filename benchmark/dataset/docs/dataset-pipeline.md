# Python Contract Dataset Pipeline

This pipeline parses and normalizes Python datasets with explicit contracts:

- `python-by-contract-corpus`
- `crosshair/examples`

It produces:

- pre-clean snapshot (`raw/`)
- cleaning preview checkpoint (when `--apply-cleaning` is not set)
- post-clean snapshot (`clean/`)
- rejects with reasons (`rejects/`)
- lineage/manifests for reproducibility
- Dualify-compatible case export and evaluation index

## Run (preview checkpoint only)

```bash
PYTHONPATH=src python -m dualify.dataset_pipeline \
  --python-by-contract-path /path/to/python-by-contract-corpus \
  --crosshair-examples-path /path/to/CrossHair/crosshair/examples \
  --output-dir benchmark/dataset/runs
```

## Run (apply cleaning after confirmation)

```bash
PYTHONPATH=src python -m dualify.dataset_pipeline \
  --python-by-contract-path /path/to/python-by-contract-corpus \
  --crosshair-examples-path /path/to/CrossHair/crosshair/examples \
  --output-dir benchmark/dataset/runs \
  --apply-cleaning
```

## Output structure

- `benchmark/dataset/runs/<run_stamp>/raw/`
  - `canonical_records.json(.jsonl)`
  - `cleaning_decisions_preview.json`
  - `dualify_cases.json`
  - `evaluation_index.jsonl`
- `benchmark/dataset/runs/<run_stamp>/clean/` (only with `--apply-cleaning`)
  - `canonical_records.json(.jsonl)`
  - `dualify_cases.json`
  - `evaluation_index.jsonl`
- `benchmark/dataset/runs/<run_stamp>/rejects/` (only with `--apply-cleaning`)
  - `rejected_records.json(.jsonl)`
- `benchmark/dataset/runs/<run_stamp>/`
  - `dataset_manifest.json`
  - `checkpoint_preview.json` (preview run)
  - `lineage.json` (clean run)
  - `cleaning_report.json` (clean run)
  - `final_report.json` (clean run)

## Where cleaned functions are stored

All accepted (cleaned) functions are stored in:

- `benchmark/dataset/runs/<run_stamp>/clean/canonical_records.json`
- `benchmark/dataset/runs/<run_stamp>/clean/canonical_records.jsonl`

Dualify-ready exports for the same cleaned subset:

- `benchmark/dataset/runs/<run_stamp>/clean/dualify_cases.json`
- `benchmark/dataset/runs/<run_stamp>/clean/evaluation_index.jsonl`

For the latest run at the moment:

- `benchmark/dataset/runs/2026_05_05_08_59_47/clean/canonical_records.json`
- `benchmark/dataset/runs/2026_05_05_08_59_47/clean/dualify_cases.json`

## Formal cleaning criteria (objective gates)

Cleaning is implemented as a deterministic conjunction of boolean gates for each parsed record.
The record is accepted iff all required gates are true and it is not a semantic duplicate.

Definitions:

- `is_python_function`: function source text is non-empty.
- `has_explicit_contract`: at least one explicit contract block was parsed (decorator or PEP316 doc contract).
- `has_type_info_minimum`: return type is explicitly annotated (not `Any`), and each collected argument type is explicit (not `Any`).
- `has_normalized_postcondition`: normalized postcondition string is non-empty.
- `contract_parseable_for_smt`: currently equivalent to non-empty normalized postcondition.
- `non_trivial_contract`: normalized postcondition is not one of trivial tautologies (`""`, `ret==ret`, `true`, `(true)`).
- `deduplicated_by_semantic_key`: key is `sha256(function_source + normalized_postcondition)[:16]`.
- `duplicate_reject`: true when the semantic key was already accepted earlier in the run.

Acceptance rule:

```text
accept(record) =
  is_python_function
  AND has_explicit_contract
  AND has_type_info_minimum
  AND has_normalized_postcondition
  AND non_trivial_contract
  AND (NOT duplicate_reject)
```

Rejection logging:

- `rejects/rejected_records.json` stores per-record reject reasons.
- `cleaning_report.json` stores the histogram of reject reasons over the run.

Detailed numeric attrition report for the latest run:

- `benchmark/dataset/docs/dataset-filtering-summary.md`
