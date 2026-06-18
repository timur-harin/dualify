# Sampling protocol for `benchmark/real/`

This document describes how the `benchmark/real/` family is sampled and
annotated. It implements the third deliverable of Milestone M2 in
[ICSE-2027-readiness-review.md](../docs/review/ICSE-2027-readiness-review.md):
50–100 Python functions sampled from PyPI top-1000 packages, *without*
contracts, scored by two human annotators using the Polikarpova-style
relevant / wrong / irrelevant scheme on Dualify's p01 output.

The work is kept in `m2-real-benchmark/` (outside `benchmark/`) on purpose, so
that it does not collide with the parallel session that is editing
`benchmark/lifted/` and `benchmark/dataset/`. Once both lines of work are
settled, the curated cases move into `benchmark/real/` and the downloaded
package sources are dropped.

## 1. Why a separate "real" family

The `lifted` family is a *gold* benchmark: functions that already ship with
`icontract` reference contracts, hand-lifted into the Dualify fragment. By
construction it over-represents well-specified code. The `real` family
corrects this selection bias. It samples ordinary library functions that were
never written with verification in mind, so the natural-language source is
whatever docstring or comment the author happened to write. This is the
population Dualify will face in deployment, and it is the population an ICSE
reviewer will ask about under external validity (§5.3 of the review).

We do not have a reference contract for these functions. We therefore cannot
measure equivalence against a ground truth. Instead, following Polikarpova et
al. (2009), we measure the *quality of the extracted spec itself*: two
annotators judge whether each clause that p01 produced is relevant, wrong, or
irrelevant with respect to the function's actual behaviour.

## 2. Source population

- **Frame:** the PyPI top-1000 packages by download count.
- **Inclusion filters at the package level:**
  1. Pure-Python (a wheel or sdist that contains `.py` sources; no
     C-extension-only packages).
  2. Permissive licence (MIT / BSD / Apache-2.0 / PSF), so the source can be
     redistributed inside the benchmark.
  3. Carries inline type annotations on at least some public functions.
- **Exclusion at the package level:**
  - Any package that imports a contract library (`icontract`, `deal`,
    `dpcontracts`, `crosshair`). Those functions already carry contracts and
    belong to the `lifted` lineage, not here.

The concrete curated list of packages is in `tools/packages.txt`. It was
chosen to favour small, pure, self-contained utility functions (string
manipulation, version arithmetic, numeric helpers), because those are the
functions whose behaviour a single annotator can judge confidently and whose
contracts are at least *near* the Dualify fragment. Packages that are mostly
I/O, framework glue, or heavy class hierarchies yield few annotatable
functions and are deliberately under-weighted.

## 3. Function-level discovery and filters

Each package source is run through `dualify.discovery.discover_repo_cases`,
which already enforces the two hard requirements:

- **Explicit type annotations on every parameter and the return type.**
  Un-annotated functions are silently skipped.
- **An informal spec** taken from the comment block directly above the
  function, or, when there is none, the docstring.

On top of discovery we apply the following sampling filters (in
`tools/sample.py`):

1. `has_meaningful_informal_spec` — drop cases whose informal spec is empty,
   a formatting directive (`fmt: on`/`fmt: off`), shorter than 4 tokens, or
   the synthesised placeholder `Describe behavior of function '...'.`. This is
   the same defect §4.5 of the review found in `dualify_cases.json`.
2. `not dunder` — drop `__init__`, `__repr__`, and other dunder methods; their
   behaviour is conventional and not interesting to annotate.
3. `not private_noise` — keep one-underscore helpers (they are real code) but
   drop test functions (`test_*`) and `_`-only names.
4. `arity_ok` — drop nullary functions and functions with more than five
   parameters (the latter are almost always configuration glue).
5. `returns_something` — drop functions annotated `-> None`; with no return
   value there is no postcondition over `ret` to extract, so p01 has nothing to
   say.

The surviving cases are written to `cases/candidates.jsonl`, one
`BenchmarkCase` per line, tagged with its source package.

## 4. Stratification and selection

We do **not** want a benchmark that is all string helpers. From the candidate
pool we stratify by the return type into four strata and sample within each:

- **boolean** (`-> bool`): predicates. p01 should produce a crisp
  postcondition; these are the cleanest annotation targets.
- **numeric** (`-> int | float`): arithmetic and counting helpers.
- **string** (`-> str`): text manipulation.
- **structured** (everything else: containers, dataclasses, optionals): the
  hard tail, where p01 is expected to degrade. We keep a minority of these on
  purpose, so the benchmark is not artificially easy.

Target size is 60 functions: 15 per stratum where the pool allows, drawn in
package order to keep the sample reproducible (no randomness, so a re-run on
the same package set reproduces the same selection). Where a stratum is thin,
its quota is redistributed to the structured tail. The selected ids are
recorded in `cases/selected.jsonl`.

## 5. Extraction (p01) — deferred to a hosted model

For each selected case we run **only p01** (`extract_spec_logic`) at temperature
0. We deliberately do not run p02–p05: the `real` family scores the
*spec-to-logic* extraction in isolation, because that is the channel the
annotators can judge without a reference contract. The model name, base URL,
and a content hash of the inputs are recorded with every result so the run can
be replayed (§4.7 of the review asks for exactly this).

**This step is deferred.** A pilot run against the only locally-available model,
Ollama `qwen3.5:9b`, returned a vacuous `ret == ret` postcondition on every
case — including trivially extractable ones such as semver `_cmp` whose spec is
"Return negative if a<b, zero if a==b, positive if a>b". A 9B model is not
representative of the GPT-/Claude-class models a deployment would use (review
§5.3), so those pilot results were discarded rather than recorded as findings.
The extraction must instead run against a properly-sized hosted model. The
tooling (`tools/run_p01.py`) is ready and provider-agnostic: point
`DUALIFY_PROVIDER=openai`, `DUALIFY_BASE_URL`, and `DUALIFY_API_KEY` (or
`DUALIFY_MODEL` for a larger Ollama model) at the server and re-run. Results
land in `cases/p01_results.jsonl` with `domain_constraints`, `postcondition`,
`confidence`, the `degraded` flag, and the `extraction_trace`.

One observation from the pilot is worth keeping regardless of model: p01 emitted
`ret == ret` with `degraded=False` and `confidence=unknown`. The `degraded` flag
fires only on a *parse* failure, not on *semantic vacuity*, so a tautological
postcondition passes through unflagged. This is the same blind spot §4.1 of the
review identified in `check_equivalence`, surfacing one phase earlier. The
annotation scheme below catches it: such a postcondition is labelled
*irrelevant*.

### 5b. Gold reference layer (inference-free)

Independently of p01, every selected case carries a hand-written **gold
reference** in `cases/reference.jsonl`. For each function we read its source and
record:

- `behavior_summary` — one sentence of plain-English true behaviour.
- `reference_pre` / `reference_post` — the true contract in the Dualify fragment,
  or `null` when the behaviour is out of fragment.
- `fragment_fit` ∈ {`in`, `near`, `out`} (as in §6).
- `profile` — the one-sentence in-scope / out-of-scope / observable note.
- `difficulty` ∈ {`easy`, `medium`, `hard`}.

This reference is the ground truth an annotator consults when labelling p01's
clauses *relevant / wrong / irrelevant*. It is produced without any LLM
inference and so can be drafted now, before the hosted-model p01 run.

## 6. Annotation scheme (Polikarpova-style)

Each *clause* that p01 emits — every entry of `domain_constraints` and the
single `postcondition` — is judged independently by two annotators. Following
Polikarpova et al. (2009), the label set is:

- **relevant** — the clause is a true statement about the function's behaviour
  and is non-trivial (it actually constrains inputs or outputs).
- **wrong** — the clause is false: there is an input the function accepts (or a
  result it returns) for which the clause does not hold.
- **irrelevant** — the clause is true but vacuous or off-topic: a tautology
  (`ret == ret`), a restatement of the type signature, or a constraint about
  something the function does not depend on.

A case also carries a case-level judgement:

- `degraded` — taken directly from p01; if true, p01 itself reported that it
  fell back to a tautology, and the clause labels should reflect that
  (typically one irrelevant postcondition).
- `fragment_fit` ∈ {`in`, `near`, `out`} — whether the function's *true*
  contract is expressible in the Dualify fragment (`in`), expressible after a
  small approximation (`near`), or fundamentally outside it (`out`, e.g.
  requires quantifiers, higher-order calls, or floating-point reasoning). This
  records the §4.5 `reference_in_fragment` stratification at annotation time.

Per-clause and per-case agreement between the two annotators is computed with
Cohen's κ. Disagreements are adjudicated by discussion and the resolved label
is stored in `adjudicated`. This is the artefact Study A (§7, M3) consumes.

### Annotation file format

One YAML file per case under `annotations/`, named after the `benchmark_id`
with separators flattened to `_`. The schema is:

```yaml
benchmark_id: <id>
package: <pypi package>
signature: <signature>
informal_spec: <the natural-language source p01 saw>
function_source: |
  <source>
p01:
  domain_constraints: [ ... ]
  postcondition: <expr>
  confidence: <low|medium|high|unknown>
  degraded: <bool>
fragment_fit: in | near | out          # case-level
annotations:
  annotator_1:                          # drafted here as "claude-opus" stand-in
    postcondition: relevant | wrong | irrelevant
    domain_constraints: [relevant|wrong|irrelevant, ...]
    note: <one sentence justifying the hardest call>
  annotator_2:                          # left empty for the human second pass
    postcondition: null
    domain_constraints: []
    note: ""
adjudicated:
  postcondition: null
  domain_constraints: []
```

The first annotator column is drafted in this session (clearly labelled as a
machine-assisted draft, to be confirmed by a human). The second column is left
empty for the human annotator, as M2 requires two independent passes.

## 7. Reproducibility

Everything here is deterministic given the package set:

- `tools/packages.txt` pins the packages; `tools/sample.py` pins the filters
  and selection order; p01 runs at temperature 0.
- `tools/download.sh` records the exact versions it fetched into
  `packages/MANIFEST.txt` (package, version, licence).
- p01 results carry `{model, base_url, prompt_sha256}`.

The only non-determinism is the LLM itself (Ollama `format: json` is not
guaranteed bit-stable across model builds, per §5.2 of the review). The
recorded model digest lets a reader detect drift.

## References

- Polikarpova, Ciupa, Meyer (2009). A comparative study of programmer-written
  and automatically inferred contracts. *ISSTA 2009*.
- Knüppel, Schaer, Schaefer (2021), as cited in the readiness review, for the
  mutation-adequacy companion (Study B), which reuses the same case pool.
