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
| Reference contract expressible in fragment (`in_fragment`) | 40 true, 0 false |
| Correct vs. bug-injected implementation | 38 correct, 2 incorrect |
| Flagged `needs_attention` (reviewer wants a second look) | 8 |

**All 40 records are `in_fragment: true`.** Four records (`gcd`, `decode`,
`smallest_two`, `matches`) were previously labeled `in_fragment: false` because
their *full* informal intent needs constructs outside the fragment (GCD
maximality, a 7-segment lookup table, `Optional`/`None` second-smallest
semantics, anagram/edit-distance matching). Each now carries a **sound,
in-fragment, weaker-than-intent reference** — the same "weaker-but-checkable"
philosophy already used for `average` — and the part that is intentionally not
encoded is documented in the record's `profile`/`notes`. This gives a single
clean denominator of 40 for gold scoring.

### Bug-injected (should-disagree) records

Two records carry a deliberately incorrect implementation (`benchmark_id`
contains `incorrect`): `next_departure` (wrong modulo) and `count_flips`
(unhandled empty directions). Their `reference_pre`/`reference_post` describe
the **correct** contract, so these are ground-truth **should-disagree** cases:
a faithful code-channel extraction should *not* match the reference. They are
used as the positive class for inconsistency-detection baselines (LLM-as-judge
and the no-SMT baseline).

> Uniqueness note: five function names recur across variants (`double`, `swap`,
> `even_fibb`, `perimiter_length`, `next_departure`). Records are keyed and
> looked up by the unique `benchmark_id` (and the YAML file stem, which equals
> the matching `lifted_auto_eval` `.py` stem), never by bare `qualname`.

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
2. **Seed** (`dataset_lift.py`, via the editor's prepopulation) — prepopulate
   `informal_spec` (formal directives stripped), and lift `reference_pre` /
   `reference_post` from the corpus contract, rewriting `__return__`/`result` →
   `ret`, `implies` → `Implies`.
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

## Scoring

`dualify.gold_scoring` loads these YAMLs and scores p01/p02 extractions against
`reference_pre` / `reference_post` (or `reference_normalized` when present).
The benchmark runner attaches per-case `gold_scoring` and run-level
`summary.gold_scoring` counters (`pre_exact`, `post_exact`,
`contract_equivalent` for spec and code separately). Re-score an existing run
without LLM calls:

```bash
poetry run python -m dualify.runner --score-gold-json results/lifted_auto_eval_*.json
```
