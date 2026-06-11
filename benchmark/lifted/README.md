# `benchmark/lifted/` — the Dualify gold benchmark

This directory is the **gold benchmark**: a hand-curated set of Python
functions, each carrying a human-confirmed
*reference contract* written inside the Dualify SMT fragment, a one-sentence
verification *profile*, and a known in-/out-of-fragment label. Unlike the raw
`benchmark/dataset/` corpus (whose `informal_spec` fields are noisy and whose
contracts are frequently out of fragment), every record here has been read and
signed off by a human reviewer.

One function = one YAML file, named after a filesystem-safe form of its
`benchmark_id`.

## This release: 40 confirmed records

The first version of the gold benchmark ships the **40 records with
`status: confirmed`**. The remaining drafts in the curation pool
(`status: unreviewed`) are deliberately *not* part of this release — they are
AI-seeded drafts awaiting human review and will land in a later revision.

| Dimension | Breakdown (of the 40) |
|---|---|
| Source corpus | 23 `python_by_contract`, 17 `crosshair_examples` |
| Reference contract expressible in fragment (`in_fragment`) | 36 true, 4 false |
| Correct vs. bug-injected implementation | 38 correct, 2 incorrect |
| Flagged `needs_attention` (reviewer wants a second look) | 13 |

`in_fragment: false` is a legitimate *negative* label: the reviewer confirmed
that the function's real contract cannot be faithfully expressed in the Dualify
fragment (e.g. it needs `min`, multiset subtraction, or `Optional`/`None`
semantics). Those records carry a best-effort `reference_post` for context but
set `reference_normalized: null`.

## Provenance

Records are lifted from two contracted-Python corpora (see
[`benchmark/dataset/docs/benchmark-dataset-sources.md`](../dataset/docs/benchmark-dataset-sources.md)):

- **Python-by-Contract Corpus** (`icontract` pre/postconditions) —
  <https://github.com/mristin/python-by-contract-corpus>
- **CrossHair examples** (PEP316 / `icontract` / `deal` contracts) —
  <https://github.com/pschanely/CrossHair/tree/main/crosshair/examples>

The candidate pool is the 202-record clean set in
`benchmark/dataset/runs/2026_05_05_08_59_47/clean/`.

## Curation protocol

The tooling that produced these files lives in
[`tools/gold_editor/`](../../tools/gold_editor/) (Streamlit editor + scripts;
see its README for the field-by-field reference and the sampling/filtering
rules). The pipeline per candidate:

1. **Filter** — drop candidates whose `informal_spec` is junk
   (`fmt: on`, empty, < 10 chars) or that are CrossHair bug-detection examples.
2. **Seed** (`seed_drafts.py`) — prepopulate `informal_spec` (formal directives
   stripped), and lift `reference_pre` / `reference_post` from the corpus
   contract, rewriting `__return__`/`result` → `ret`, `implies` → `Implies`.
   `in_fragment` is set automatically from `formula_parser.validate_formula`.
3. **AI review** (`_review_workflow.js` + `apply_reviews.py`) — an agent rewrites
   out-of-fragment formulas into the fragment where possible and records what it
   did in `notes`; status stays `unreviewed`.
4. **Human confirm** (Streamlit editor) — a reviewer reads the record, edits the
   profile/contract, and presses **Confirm**, which writes `status: confirmed`.
   The Confirm button is disabled (when `in_fragment: true`) until every formula
   passes `formula_parser.validate_formula` and `reference_post` is non-empty.

## Record schema

```yaml
benchmark_id: crosshair_examples::deal::correct_code::average.py::average
qualname: average
signature: "average(numbers: List[float]) -> float"
arg_types:
  numbers: List[float]
return_type: float
informal_spec: "Behavior of average"          # cleaned natural-language spec
informal_spec_raw: "Behavior of average"       # spec before cleaning
function_source: "def average(...): ..."
profile: "In scope: ... Out of scope: ... Observable: ..."
in_fragment: true                              # is reference_post in the fragment?
reference_pre:                                 # one conjunct per line, `ret` = return value
  - Length(numbers) > 0
reference_post: "And(Exists(...), Exists(...))" # single Boolean expression in `ret`
notes: "..."                                   # reviewer / AI provenance trail
needs_attention: false                         # reviewer wants a second look
status: confirmed                              # confirmed | unreviewed
reference_normalized:                          # formulas after formula_parser; null if out of fragment
  pre: [Length(numbers) > 0]
  post: "And(Exists(...), Exists(...))"
```

All formulas obey the Dualify formula contract: Z3/Python-style expressions over
signature argument names and `ret`, using
`And`/`Or`/`Not`/`Implies`/`If` and the allowed function set. Quantified records
use `ForAll`/`Exists` in the *reference* contract for human readability; these go
beyond the decidable fragment Dualify sends to Z3 and are intended as a
ground-truth oracle, not as direct solver input.

## Status

The benchmark is **data-only** at this stage: nothing in `src/` loads these
YAMLs yet. A loader that builds `BenchmarkCase`s from the gold records and scores
Dualify's p01/p02/p03 output against the reference contracts is later work.
