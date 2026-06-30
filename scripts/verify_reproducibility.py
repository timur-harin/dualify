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

Each replay runs in a fresh subprocess so Z3 solver state from earlier runs
cannot change later verdicts (e.g. timeout flakiness on ``next_departure``).

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
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


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


def _replay_hash_in_subprocess(
    *,
    run_dir: Path,
    benchmark: str,
    output_suffix: str,
) -> str:
    """Replay one transcript in a clean process; return the verdict-vector hash."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    payload = {
        "run_dir": str(run_dir.resolve()),
        "benchmark": benchmark,
        "output_suffix": output_suffix,
    }
    code = """
import json, sys
from pathlib import Path
sys.path.insert(0, %r)
from dualify.runner import run_experiment
from dualify.transcript import ReplayLLMClient
import hashlib

payload = json.loads(sys.stdin.read())
run_dir = Path(payload["run_dir"])
report = run_experiment(
    model="replay",
    base_url="",
    benchmark_name=payload["benchmark"],
    client_override=ReplayLLMClient.from_path(
        run_dir / "transcript.jsonl", match_by_prompt=True
    ),
    output_dir=run_dir / payload["output_suffix"],
)

rows = []
for case in sorted(report.get("results", []), key=lambda c: str(c.get("benchmark_id"))):
    smt = case.get("smt_checking", {})
    gold = case.get("gold_scoring") or {}
    spec = gold.get("spec", {}) if isinstance(gold, dict) else {}
    code = gold.get("code", {}) if isinstance(gold, dict) else {}
    rows.append((
        str(case.get("benchmark_id")),
        str(smt.get("reason")),
        bool(smt.get("equivalent")),
        bool(spec.get("contract_equivalent")),
        bool(code.get("contract_equivalent")),
    ))
print(hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest())
""" % (
        str(ROOT / "src"),
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"replay subprocess failed for {run_dir.name}/{output_suffix}: "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"replay subprocess produced no output for {run_dir.name}")
    return lines[-1]


def _verify_run(run_dir: Path, benchmark: str) -> tuple[str, bool, bool, str, list[str]]:
    transcript = run_dir / "transcript.jsonl"
    reports = sorted(run_dir.glob(f"{benchmark}_*.json"), key=lambda p: p.stat().st_mtime)
    if not transcript.exists() or not reports:
        return "SKIP", False, False, "", ["missing transcript or report"]

    committed = json.loads(reports[-1].read_text())
    artifact_problems = _check_artifacts(committed)
    hc = _hash_vector(_verdict_vector(committed))

    ha = _replay_hash_in_subprocess(
        run_dir=run_dir, benchmark=benchmark, output_suffix="_verify_a"
    )
    hb = _replay_hash_in_subprocess(
        run_dir=run_dir, benchmark=benchmark, output_suffix="_verify_b"
    )
    deterministic = ha == hb
    matches_committed = ha == hc
    ok = deterministic and matches_committed and not artifact_problems
    return ("OK" if ok else "FAIL", deterministic, matches_committed, ha, artifact_problems)


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
        try:
            status, deterministic, matches_committed, ha, artifact_problems = _verify_run(
                run_dir, benchmark
            )
        except RuntimeError as exc:
            all_ok = False
            print(f"[{run_dir.name}] FAIL  {exc}")
            continue

        if status == "SKIP":
            all_ok = False
            print(f"[{run_dir.name}] SKIP (missing transcript or report)")
            continue

        if artifact_problems:
            all_ok = False
            print(f"[{run_dir.name}] ARTIFACT FAIL:")
            for problem in artifact_problems[:5]:
                print(f"    - {problem}")

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
