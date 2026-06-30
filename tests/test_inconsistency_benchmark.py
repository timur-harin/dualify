"""Tests for the forked inconsistency-detection benchmark."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCONSISTENCY = ROOT / "benchmark" / "lifted_inconsistency"


def test_inconsistency_manifest_matches_files() -> None:
    manifest = json.loads((INCONSISTENCY / "manifest.json").read_text())
    assert manifest["n_cases"] == 40
    assert manifest["n_buggy"] == 10
    assert manifest["n_correct"] == 30
    stems = {entry["stem"] for entry in manifest["cases"]}
    py_stems = {p.stem for p in INCONSISTENCY.glob("*.py")}
    assert stems == py_stems


def test_inconsistency_buggy_labels_unique_stems() -> None:
    manifest = json.loads((INCONSISTENCY / "manifest.json").read_text())
    stems = [entry["stem"] for entry in manifest["cases"]]
    assert len(stems) == len(set(stems))
    buggy = [entry for entry in manifest["cases"] if entry["buggy"]]
    assert len(buggy) == 10
    assert all("incorrect" in entry["benchmark_id"] for entry in buggy)
