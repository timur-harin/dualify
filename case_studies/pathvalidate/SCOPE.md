# Scope — pathvalidate case study

**Repository:** https://github.com/thombashi/pathvalidate  
**Commit:** `1ca0a50fce51d5b5bd633457a72abf74dbe3112d`

## Selected functions (6)

| benchmark_id | Line | Role |
|---|---|---|
| `pathvalidate::_filename.py::validate_filename` | 277 | Validate filename; full docstring |
| `pathvalidate::_filename.py::is_valid_filename` | 347 | Boolean wrapper |
| `pathvalidate::_filename.py::sanitize_filename` | 381 | Sanitize to valid name |
| `pathvalidate::_filepath.py::validate_filepath` | 307 | Validate path |
| `pathvalidate::_filepath.py::is_valid_filepath` | 374 | Boolean wrapper |
| `pathvalidate::_filepath.py::sanitize_filepath` | 408 | Sanitize path |

## Regex filter

```
_filename.py::(validate_filename|sanitize_filename|is_valid_filename)|
_filepath.py::(validate_filepath|sanitize_filepath|is_valid_filepath)
```

## Operator mode

Interactive policy automated in `run_operator_loop.py` (LLM-as-judge): prints Dualify comparison reports, selects actions from closed menu, logs to `operator_log.jsonl`.
