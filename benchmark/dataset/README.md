# Dataset Workspace

This folder contains all dataset-related assets for contract parsing and evaluation.

## Structure

- `sources/` - downloaded upstream datasets
  - `python-by-contract-corpus/`
  - `CrossHair/`
- `docs/` - dataset sources table and pipeline guide
  - `benchmark-dataset-sources.md`
  - `dataset-pipeline.md`
- `runs/` - parsed/normalized/cleaned snapshots

## Latest parsed run

- `runs/2026_05_05_08_51_17/`
  - `raw/canonical_records.json` (full parsed snapshot)
  - `clean/canonical_records.json` (accepted after cleaning)
  - `rejects/rejected_records.json` (removed records + reasons)
  - `dataset_manifest.json` (source and pipeline metadata)
  - `lineage.json` (raw-to-clean mapping)
  - `cleaning_report.json` (objective filter summary)
  - `final_report.json` (before/after counts)
