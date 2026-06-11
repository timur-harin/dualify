# Gold-benchmark editor

A small Streamlit app for hand-curating the gold benchmark
(`benchmark/lifted/`). It walks the 202 candidate records from
`benchmark/dataset/runs/.../clean/canonical_records.json`, filters out
cases whose `informal_spec` is junk (`fmt: on`, empty, <10 chars), and
lets you write a profile + reference pre/post per function, one at a time.

## Install

The editor lives in the optional `tools` Poetry group so it doesn't slow
down the default install:

```bash
poetry install --with tools
```

## Run

```bash
poetry run streamlit run tools/gold_editor/app.py
```

The dataset path defaults to
`benchmark/dataset/runs/2026_05_05_08_59_47/clean/canonical_records.json`
and can be overridden from the sidebar.

## What you fill in per case

| Field            | Meaning                                                                                        |
|------------------|------------------------------------------------------------------------------------------------|
| `informal_spec`  | Cleaned natural-language spec (prepopulated with `pre:` / `post:` directives stripped).        |
| `profile`        | One-sentence in-scope / out-of-scope / observable boundary.                                    |
| `in_fragment`    | Toggle: is the reference contract expressible in the Dualify fragment?                         |
| `reference_pre`  | One conjunct per line. Use `ret` for the return value. Validated against `formula_parser`.     |
| `reference_post` | Single Boolean expression in `ret`. Required when `in_fragment=True`.                          |
| `notes`          | Free-form, anything you'd want a future annotator to know.                                     |
| `needs_attention`| Boolean. True iff a human reviewer should pay extra attention to this card.                    |
| `status`         | `unreviewed` (draft) or `confirmed` (signed off by a human via this editor).                   |

The editor's progress counter and "Confirmed / Unconfirmed / Drafted
(unreviewed)" filter are driven off `status`, not file existence. A YAML
with no `status` field is treated as `unreviewed`. The **Confirm** button
always writes `status: confirmed`.

Cards with `needs_attention: true` get a ⚠ in the picker label, a warning
banner at the top of the right pane, and are counted separately in the
sidebar progress line. A sidebar checkbox **"Only show needs-attention"**
filters the picker to just those cards. The right pane has an editable
checkbox so you can flip the flag while reviewing -- e.g. set it on a
case you want to come back to, or untick it once you're satisfied.

### Prepopulation (PEP316 / icontract specs)

Many dataset entries already carry a formal contract — either in PEP316
`pre:` / `post:` docstring directives (crosshair examples) or as
`icontract` decorators. The editor automates the boring half:

- **Spec is stripped of formulas.** PEP316 `pre:` / `post:` / `raises:`
  directives (and their indented continuations) are removed from
  `informal_spec`, leaving only the prose. The stripped lines stay
  visible on the left under "Stripped formal directives" so nothing
  is hidden.
- **Reference contract is prefilled.** `reference_pre` is seeded from
  `normalized_domain_constraints` (one conjunct per line) and
  `reference_post` from `normalized_postcondition`, each passed through
  a small lifter that rewrites `__return__` → `ret`, `result` → `ret`,
  and `implies(...)` → `Implies(...)`.
- **Validator still has the last word.** Any leftover Python `and` /
  `or` / `not`, comprehensions, tuple equality, etc. surface as
  inline errors so the operator knows exactly what to rewrite.
- **`self_*` is admitted automatically.** For class methods, every
  `self.foo` reference found in the spec / source / contracts admits
  `self_foo` as a known identifier — mirroring
  `p01_spec_to_logic._extract_self_symbols`.

The **Confirm** button stays disabled (when `in_fragment=True`) until all
formulas pass `formula_parser.validate_formula` and `reference_post` is
non-empty. A **Reset to dataset prepopulation** button discards
in-session edits for the current card and re-applies the lifted defaults.

## Output

Each confirmed case becomes a YAML file under `benchmark/lifted/`:

```
benchmark/lifted/<safe-benchmark-id>.yaml
```

with the schema:

```yaml
benchmark_id: python_by_contract::correct::aoc2020::day_10_adapter_array.py::histogram_differences
qualname: histogram_differences
file: python_by_contract/correct/aoc2020/day_10_adapter_array.py
signature: "histogram_differences(adapters: List[int]) -> HistogramOfDeltas"
arg_types:
  adapters: List[int]
return_type: HistogramOfDeltas
informal_spec: "Compute the histogram of jolt differences in ``adapters``."
informal_spec_raw: "Compute the histogram of jolt differences in ``adapters``."
function_source: |
  def histogram_differences(adapters):
      ...
profile: |
  In scope: count of jolt-difference buckets for a non-empty unique
  positive-integer adapter list. Out of scope: heap state of the returned
  HistogramOfDeltas. Observable: the bucket counts.
in_fragment: true
reference_pre:
  - Length(adapters) > 0
  - And(adapters_distinct, all_nonneg)
reference_post: "Length(ret) == Length(adapters) + 1"
notes: "Rewrote `all(... >= 0)` as a single nonneg flag because comprehensions are forbidden in the fragment."
reference_normalized:
  pre:
    - Length(adapters) > 0
    - And(adapters_distinct, all_nonneg)
  post: "Length(ret) == Length(adapters) + 1"
```

The sidebar shows global progress (`confirmed / total`) and a per-case filter
(All / Unconfirmed / Confirmed) plus a substring search. **Unconfirm** lives
in a "Danger zone" expander on confirmed cards and permanently deletes the
on-disk YAML (in-session edits are preserved).

## After curation

A small downstream script can assemble the per-file YAMLs into a single
consolidated JSON — that conversion is deliberately not part of the editor
so the editor's blast radius stays limited to `benchmark/lifted/`.
