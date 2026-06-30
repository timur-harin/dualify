#!/usr/bin/env python3
"""Verify a Dualify campaign is reproducible offline, with no LLM calls.

For each recorded run in a campaign directory this script:

1. Checks the committed run report carries the durable artifacts a reviewer
   needs: a per-case ``fingerprint`` (source/spec checksums), extracted
   ``spec_to_logic`` / ``code_to_logic`` formulas, and ``smt_checking`` verdicts.
2. Replays the frozen LLM transcript twice through the live pipeline (Z3 +
   parser, zero network) and confirms the verdict vector is byte-stable, i.e.
   the equivalence verdicts are fully determined by the saved LLM responses.
3. Confirms the replayed verdicts match the committed report.

This is what lets reviewers re-derive every equivalence verdict deterministically
from the repository alone, without API keys.

Usage:

    PYTHONPATH=src python scripts/verify_reproducibility.py \
        results/campaigns/lifted_auto_eval__qwen_local
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dualify.runner import run_experiment  # noqa: E402
from dualify.transcript import ReplayLLMClient  # noqa: E402


def _verdict_vector(report: dict) -> list[tuple]:
    rows: list[tuple] = []
    for case in sorted(report.get("results", []), key=lambda c: str(c.get("benchmark_id"))):
        smt = case.get("smt_checking", {})
        gold = case.get("gold_scoring") or {}
        spec = gold.get("spec", {}) if isinstance(gold, dict) else {}
        code = gold.get("code", {}) if isinstance(gold, dict) else {}
        rows.append(
            (
                str(case.get("benchmark_id")),
                str(smt.get("reason")),
                bool(smt.get("equivalent")),
                bool(spec.get("contract_equivalent")),
                bool(code.get("contract_equivalent")),
            )
        )
    return rows


def _hash_vector(vector: list[tuple]) -> str:
    return hashlib.sha256(json.dumps(vector, sort_keys=True).encode()).hexdigest()


def _check_artifacts(report: dict) -> list[str]:
    problems: list[str] = []
    for case in report.get("results", []):
        bid = case.get("benchmark_id", "?")
        if not isinstance(case.get("fingerprint"), dict):
            problems.append(f"{bid}: missing fingerprint")
        elif not case["fingerprint"].get("source_sha256"):
            problems.append(f"{bid}: fingerprint lacks source_sha256")
        for key in ("spec_to_logic", "code_to_logic", "smt_checking"):
            if not isinstance(case.get(key), dict):
                problems.append(f"{bid}: missing {key}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign_dir")
    args = parser.parse_args()

    campaign = Path(args.campaign_dir).resolve()
    aggregate_path = campaign / "aggregate.json"
    if not aggregate_path.exists():
        print(f"ERROR: {aggregate_path} not found", file=sys.stderr)
        return 2
    meta = json.loads(aggregate_path.read_text())
    benchmark = meta.get("benchmark", "lifted_auto_eval")

    run_dirs = sorted(campaign.glob("run_*"))
    if not run_dirs:
        print(f"ERROR: no run_* dirs under {campaign}", file=sys.stderr)
        return 2

    all_ok = True
    for run_dir in run_dirs:
        transcript = run_dir / "transcript.jsonl"
        reports = list(run_dir.glob(f"{benchmark}_*.json"))
        if not transcript.exists() or not reports:
            print(f"[{run_dir.name}] SKIP (missing transcript or report)")
            all_ok = False
            continue
        committed = json.loads(reports[0].read_text())

        artifact_problems = _check_artifacts(committed)
        if artifact_problems:
            all_ok = False
            print(f"[{run_dir.name}] ARTIFACT FAIL:")
            for p in artifact_problems[:5]:
                print(f"    - {p}")

        # Two independent replays, zero LLM calls. Hash-keyed matching makes
        # replay order-independent so it reproduces the recorded control flow.
        replay_a = run_experiment(
            model="replay",
            base_url="",
            benchmark_name=benchmark,
            client_override=ReplayLLMClient.from_path(transcript, match_by_prompt=True),
            output_dir=run_dir / "_verify_a",
        )
        replay_b = run_experiment(
            model="replay",
            base_url="",
            benchmark_name=benchmark,
            client_override=ReplayLLMClient.from_path(transcript, match_by_prompt=True),
            output_dir=run_dir / "_verify_b",
        )
        va, vb, vc = (
            _verdict_vector(replay_a),
            _verdict_vector(replay_b),
            _verdict_vector(committed),
        )
        ha, hb, hc = _hash_vector(va), _hash_vector(vb), _hash_vector(vc)
        deterministic = ha == hb
        matches_committed = ha == hc
        status = "OK" if (deterministic and matches_committed and not artifact_problems) else "FAIL"
        if status != "OK":
            all_ok = False
        print(
            f"[{run_dir.name}] {status}  deterministic={deterministic} "
            f"matches_committed={matches_committed} verdict_sha={ha[:12]}"
        )

    print("\nRESULT:", "ALL REPRODUCIBLE" if all_ok else "PROBLEMS FOUND")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
