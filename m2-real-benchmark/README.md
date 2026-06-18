# m2-real-benchmark — working area for the `benchmark/real/` family

Work-in-progress for the third deliverable of Milestone M2 (see
[../docs/review/ICSE-2027-readiness-review.md](../docs/review/ICSE-2027-readiness-review.md)):
50–100 un-contracted PyPI functions with two-annotator, Polikarpova-style
annotations on Dualify's p01 output.

Kept outside `benchmark/` on purpose so it does not collide with the parallel
session editing `benchmark/lifted/` and `benchmark/dataset/`. Nothing here
modifies `src/` or the existing benchmark families. Once both lines of work
settle, the curated cases move into `benchmark/real/` and `packages/` is dropped.

## Read this first

- [FINDINGS.md](./FINDINGS.md) — what was produced and the headline result
  (87 % of real functions are out of the Dualify fragment).
- [sampling-protocol.md](./sampling-protocol.md) — the reproducible sampling and
  annotation protocol.

## Layout

```
tools/
  packages.txt        curated PyPI package list
  download.sh         fetch sdists -> packages/, write MANIFEST.txt
  sample.py           discover + filter + stratify -> cases/{candidates,selected}.jsonl
  run_p01.py          run p01 extraction (provider-agnostic) -> cases/p01_results.jsonl
  merge_reference.py  merge per-batch reference drafts -> cases/reference.jsonl (+ validate)
  gen_annotations.py  build per-case cards -> annotations/*.yaml
  fill_p01.py         drop p01 output into the cards (after the hosted run)
cases/
  candidates.jsonl    294 discovered, filtered candidate functions
  selected.jsonl      60 selected (15 per return-type stratum)
  reference.jsonl     hand-drafted gold reference for all 60 (the scoring key)
annotations/          60 per-case YAML cards, ready for the annotators
packages/             downloaded sdists (gitignored; reproduce with download.sh)
```

## Reproduce

```bash
bash m2-real-benchmark/tools/download.sh
poetry run python m2-real-benchmark/tools/sample.py
poetry run python m2-real-benchmark/tools/merge_reference.py   # rebuilds reference.jsonl from drafts
poetry run python m2-real-benchmark/tools/gen_annotations.py

# extraction — needs a properly-sized HOSTED model, not a local 9B:
DUALIFY_PROVIDER=openai DUALIFY_BASE_URL=… DUALIFY_API_KEY=… \
  poetry run python m2-real-benchmark/tools/run_p01.py
poetry run python m2-real-benchmark/tools/fill_p01.py
```

Note: `merge_reference.py` reads `cases/_ref_batch_{0..3}.json`, which are the
intermediate reference drafts. They were removed after the first merge; the
canonical reference is `cases/reference.jsonl`. To re-run the merge, the drafts
would need to be regenerated, or edit `reference.jsonl` directly.
