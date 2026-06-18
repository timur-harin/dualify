# Findings — sampling the `benchmark/real/` family (M2)

This note records progress on the third deliverable of Milestone M2: a `real`
benchmark family of un-contracted PyPI functions, with drafted annotations. The
work lives in `m2-real-benchmark/` to stay clear of the parallel session editing
`benchmark/lifted/` and `benchmark/dataset/`. It does not touch `src/` or the
existing benchmark families.

## Relevance to the 2026-06-18 readiness review

This work addresses two named gaps in
[ICSE-2027-readiness-review-2.md](../docs/review/ICSE-2027-readiness-review-2.md):

- **§2.4 — "The `benchmark/real/` family of uncontracted PyPI functions (M2)
  does not exist."** It now exists in draft form: a reproducible sampling
  protocol, 60 sampled functions, and a gold reference for each. The review
  rightly notes the gold benchmark is the one that matters for the 12-day paper;
  this `real` family is the *external-validity* complement, not a competitor to
  it.
- **§2.6 / first-review §5.3 — external validity ("a 3B local model / a
  contract corpus is not representative").** The headline number below — 87 % of
  ordinary library functions have no contract in the Dualify fragment — is a
  measured external-validity statement. It belongs in the threats section as a
  quantified bound on how often Dualify has anything to check on code in the
  wild, and it explains *why* the `lifted` gold set (drawn from a contract
  corpus) reads optimistically.

It does **not** produce the headline fidelity/bug-catch number the review puts on
the critical path; that comes from running the gold benchmark (§2.1, §4 of the
review) and is independent of this work.

## What was produced

- A reproducible sampling protocol ([sampling-protocol.md](./sampling-protocol.md)).
- Tooling under `tools/`: `download.sh` (fetch sdists), `sample.py` (discover +
  filter + stratify), `run_p01.py` (extraction, provider-agnostic),
  `merge_reference.py`, `gen_annotations.py`, `fill_p01.py`.
- 12 PyPI packages downloaded as sdists (`packages/MANIFEST.txt`), 294 candidate
  functions discovered (`cases/candidates.jsonl`), 60 selected (`cases/selected.jsonl`).
- A hand-drafted gold reference for all 60 cases (`cases/reference.jsonl`).
- 60 per-case annotation cards (`annotations/*.yaml`) ready for the two-annotator
  Polikarpova pass.

The selection is deterministic given the package set: 15 functions per return-type
stratum (boolean, numeric, string, structured), picked round-robin across
packages so no single library dominates. Ten of the twelve packages are
represented (packaging, pathspec, semver, wcwidth, humanize, boltons, inflection,
python-slugify, url_normalize, tomli); jmespath and more_itertools contributed no
annotatable functions after filtering.

## The headline number: real code is mostly out of fragment

For each of the 60 functions we read the source and judged whether its *true*
contract is expressible in the Dualify fragment. The result:

| fragment_fit | count | share |
|---|---|---|
| `in` (fully expressible) | 1 | 2 % |
| `near` (expressible after a small faithful approximation) | 7 | 12 % |
| `out` (needs quantifiers, regex, helper calls, object construction, …) | 52 | 87 % |

Only **8 of 60** un-contracted real functions admit even an approximate contract
in the fragment. The breakdown by stratum is uniform — even boolean predicates
are mostly `out`, because in real libraries a predicate typically delegates to a
regex (`Version.is_valid`), a Unicode table (`_is_incb_consonant`), object state
(`TreeEntry.is_dir`), or the filesystem (`append_dir_sep`).

This is the empirical content of the external-validity threat in §5.3 of the
readiness review, and it sharpens §4.5. The `lifted` family is drawn from a
contract corpus and so over-represents fragment-friendly functions; on ordinary
library code the in-fragment rate is about **13 %**. A paper that reports
agreement or kill rates only on `lifted` would overstate how often Dualify has
anything to check on code in the wild. The `real` family makes that gap
measurable.

The eight usable cases are: `semver::_cmp` (`in`); and `near` —
`semver::Version.is_compatible`, `wcwidth::wcwidth`, `wcwidth::bisearch`,
`boltons::removeprefix`, `python-slugify::smart_truncate`,
`wcwidth::_apply_sgr_wrap`, `humanize::_ngettext_noop`. Seven of these eight
reference formulas pass Dualify's own `normalize_formula` + `validate_formula`;
the eighth (`is_compatible`) is well-formed but mentions version components held
as object state (`self_patch`) that the validator's name set does not derive from
the source, which is itself a small note for the well-formedness work in M1.

By difficulty the sample is honest about being hard: 8 easy, 25 medium, 27 hard.

## Two incidental findings about the pipeline

1. **p01 reports `ret == ret` with `degraded=False`.** A pilot p01 run against
   the only locally-available model (Ollama `qwen3.5:9b`) returned a tautological
   postcondition on every case, including the trivially extractable
   `semver::_cmp` ("Return negative if a<b, zero if a==b, positive if a>b"). The
   model output passed validation (a tautology is well-formed), so no repair ran
   and `degraded` stayed false with `confidence=unknown`. The `degraded` flag
   fires on a *parse* failure, not on *semantic vacuity*. This is the §4.1
   vacuous-equivalence blind spot surfacing one phase earlier, in extraction. The
   annotation scheme already accounts for it: a `ret == ret` postcondition is
   labelled *irrelevant*.

   The pilot ran against `main`'s p01, which has no semantic-vacuity guard. The
   `b00dfda` push on `m2-gold-bench` adds exactly such a guard
   (`_post_quality_issues`, rejecting tautological `ret == ret` and
   quantifier-to-`ret` postconditions at extraction time, per review-2 §0b), so
   this observation corroborates that fix rather than reporting a new bug on the
   trunk-to-be. The note worth carrying is that the guard belongs on `main` too,
   and that the `real` cards make a good regression set for it: 52 of 60 functions
   *should* extract to something the guard would have to let through or honestly
   degrade on.

   These pilot numbers were **discarded, not recorded**: a 9B model is not
   representative of the GPT-/Claude-class models a deployment would use, so its
   failure rate is not a finding about Dualify. The extraction step is deferred to
   a hosted model; the tooling is ready and provider-agnostic.

2. **The formula parser accepts a Python tuple literal.** The reference
   `ret == (singular, plural)` for `humanize::_ngettext_noop` passed `main`'s
   `validate_formula`. Tuple construction is outside the intended fragment, so
   this is a permissiveness gap worth a regression test alongside the M1
   well-formedness work. It should be re-checked against the expanded fragment on
   `m2-gold-bench` (which adds `Extract`/`Unit`/`Tuple`-sort handling), since the
   intended behaviour there may differ.

## What remains (needs the hosted model)

The Polikarpova *relevant / wrong / irrelevant* labels are scored on p01's
output, which we do not yet have at representative quality. The pipeline is
staged so the remaining work is mechanical once a server is available:

1. Point `tools/run_p01.py` at a hosted model
   (`DUALIFY_PROVIDER=openai DUALIFY_BASE_URL=… DUALIFY_API_KEY=…`, or a larger
   Ollama model via `DUALIFY_MODEL`) and run it over `cases/selected.jsonl`.
2. `tools/fill_p01.py` drops the clauses into the annotation cards.
3. Two annotators label each clause against the gold reference already in each
   card; disagreements are adjudicated and Cohen's κ reported.

The gold reference drafted here is the scoring key for step 3, and it is what an
annotator consults to decide whether a p01 clause is relevant, wrong, or
irrelevant. It required no LLM inference and so is complete now.

## A caveat on the sample itself

Favouring small utility packages keeps the functions judgeable, but it also
means the sample is not a uniform draw from the top-1000 — it is biased towards
string/number/version helpers. The 87 % `out` rate would, if anything, be higher
on a uniform draw (framework and I/O code is even less fragment-friendly). The
sample is therefore a conservative, not optimistic, estimate of in-fragment
coverage. Before this family is promoted into `benchmark/real/`, the package list
should be widened and a second annotator should re-judge `fragment_fit`
independently, since that label drives every downstream stratification.
