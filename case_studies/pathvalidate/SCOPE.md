# Scope — anonymized input-validation case study

**Repository:** anonymized open-source Python input-validation library  
**Commit:** pinned in the local checkout; de-anonymized after review

## Selected functions (6)

| benchmark_id | Line | Role |
|---|---|---|
| `oss_validation::_filename.py::validate_filename` | 277 | Validate filename; full docstring |
| `oss_validation::_filename.py::is_valid_filename` | 347 | Boolean wrapper |
| `oss_validation::_filename.py::sanitize_filename` | 381 | Sanitize to valid name |
| `oss_validation::_filepath.py::validate_filepath` | 307 | Validate path |
| `oss_validation::_filepath.py::is_valid_filepath` | 374 | Boolean wrapper |
| `oss_validation::_filepath.py::sanitize_filepath` | 408 | Sanitize path |

## Regex filter

```
_filename.py::(validate_filename|sanitize_filename|is_valid_filename)|
_filepath.py::(validate_filepath|sanitize_filepath|is_valid_filepath)
```

## Operator mode

Interactive policy automated in `run_operator_loop.py` (LLM-as-judge): prints Dualify comparison reports, selects actions from closed menu, logs to `operator_log.jsonl`.
