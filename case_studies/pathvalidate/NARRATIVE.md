# Deep-dive: boolean filename validator `max_len` semantics

## Context

Dualify scanned six entry points in an anonymized OSS input-validation package.
Automated cross-check flagged the boolean filename validator with
`formula_parse_error` (LLM post used `Contains` on a
non-sequence parameter). The operator judge classified this as **UN** (tool
limit) and proceeded with **manual doc review** — the intended workflow when
extraction is weak but the mismatch hypothesis remains plausible.

## Observed doc/code gap (TP)

The strict filename validator defaults `max_len=255`.  
The boolean filename validator passes `max_len=-1` when the argument is `None`, which
selects the **platform** byte limit (e.g. 4096 on Linux) — not 255.

The original boolean validator docstring only listed `filename` and
`platform`, so readers assuming parity with the strict validator would mis-test
long names.

## Witness (executable)

```python
long_name = "a" * 300
validate_filename(long_name)              # ValidationError (255 cap)
is_valid_filename(long_name, platform="Linux")  # True
```

## Operator actions

1. **investigate_instrumentation** (automated judge on weak Z3 outcome)
2. **refine_spec** (manual): expand boolean validator Args in docstring
3. **add_test_case** (manual): `test/test_dualify_case_study.py`

## Secondary TP: `sanitize_*` Raises section

Docstrings claimed `ValueError` on failure. Implementation propagates
`ValidationError` (e.g. via `null_value_handler=raise_error`). Patched Raises
sections in `_filename.py` and `_filepath.py`; regression test added.

## Impact

- 2 docstring corrections + 2 tests in `patches/pathvalidate-doc-alignment.patch`
- Demonstrates Dualify + operator loop surfacing **documentation drift** that
  unit tests did not encode, without requiring Z3 equivalence on the first pass

## Limits (honest)

- Wrapper functions (`sanitize_*`, `is_valid_*`) often yield `low_confidence_parse`
  or vacuous `ret == ret` extractions — SMT cross-check alone is insufficient
- Full sanitization semantics need richer fragments or human review
