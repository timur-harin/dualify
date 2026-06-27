# Improved benchmark run (2026-06-16)

| Metric | Baseline avg(3) | Improved #1 | Improved #2 | Improved #3 |
|---|---:|---:|---:|---:|
| SMT equivalent /40 | 9.3 | 4 | 5 | 7 |
| Spec degraded /40 | 18.0 | 5 | 7 | 14 |
| Code degraded /40 | 14.3 | 8 | 9 | 20 |
| formula_parse_error | 21.3 | 32 | 29 | 24 |
| Spec pre exact /40 | 13.0 | 14 | 15 | 12 |
| Spec post exact /40 | 3.0 | 3 | 3 | 3 |
| Code pre exact /40 | 11.7 | 14 | 12 | 12 |
| Code post exact /40 | 5.0 | 4 | 4 | 4 |
| Weak spec post ret==ret /40 | 14.7 | 2 | 5 | 11 |

### P03-only re-eval on run #3 extractions (no new LLM calls)

After latest `formula_parser` + `p03_smt_checking` fixes, re-running SMT on the **same** run #3 extractions:

| Metric | Baseline avg(3) | Run #3 (old p03) | Re-eval (new p03) |
|---|---:|---:|---:|
| SMT equivalent /40 | 9.3 | 7 | **9** |
| formula_parse_error | 21.3 | 24 | **3** |

Parse-error fixes recover **21 cases** that previously failed in SMT (24 → 3). The 3 remaining are malformed LLM formulas (`Concat(ForAll(...))`, string arithmetic, nested-sequence membership).

Improved run IDs:
- `lifted_auto_eval_2026_06_16_14_33_36`
- `lifted_auto_eval_2026_06_16_14_49_32`
- `lifted_auto_eval_2026_06_16_14_57_42`
