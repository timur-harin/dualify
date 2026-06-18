"""Run p01 (spec_to_logic) on the selected real-benchmark cases.

Only p01 is run: the real family scores spec-to-logic extraction in isolation
(see sampling-protocol.md §5). Results, with model metadata and an input hash
for replay detection, are written to ../cases/p01_results.jsonl.

    poetry run python m2-real-benchmark/tools/run_p01.py
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from dualify.ollama_client import OllamaClient
from dualify.phases.p01_spec_to_logic import extract_spec_logic

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CASES_DIR = ROOT / "cases"

MODEL = os.environ.get("DUALIFY_MODEL", "qwen3.5:9b")
BASE_URL = os.environ.get("DUALIFY_BASE_URL", "http://127.0.0.1:11434")


def input_hash(case: dict) -> str:
    blob = " ".join(
        [
            case["signature"],
            case["informal_spec"],
            case.get("extra_context", ""),
            case["return_type"],
        ]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def main() -> None:
    selected = [json.loads(line) for line in (CASES_DIR / "selected.jsonl").open()]
    client = OllamaClient(model=MODEL, base_url=BASE_URL, timeout_sec=90)

    out_path = CASES_DIR / "p01_results.jsonl"
    # Resume support: skip ids already processed.
    done: set[str] = set()
    if out_path.exists():
        for line in out_path.open():
            with contextlib.suppress(json.JSONDecodeError, KeyError):
                done.add(json.loads(line)["benchmark_id"])

    with out_path.open("a", encoding="utf-8") as fh:
        for i, case in enumerate(selected, 1):
            bid = case["benchmark_id"]
            if bid in done:
                print(f"[{i:2d}/{len(selected)}] skip (done) {bid}")
                continue
            t0 = time.time()
            try:
                result = extract_spec_logic(
                    client,
                    benchmark_id=bid,
                    signature=case["signature"],
                    informal_spec=case["informal_spec"],
                    return_type=case["return_type"],
                    extra_context=case.get("extra_context", ""),
                )
                record = dataclasses.asdict(result)
                record["error"] = None
            except Exception as exc:  # noqa: BLE001 - log and keep going
                record = {
                    "benchmark_id": bid,
                    "args": [],
                    "return_type": case["return_type"],
                    "domain_constraints": [],
                    "postcondition": "",
                    "confidence": "unknown",
                    "notes": "",
                    "degraded": True,
                    "degraded_reason": "extraction_exception",
                    "extraction_trace": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            dt = time.time() - t0
            record["package"] = case["package"]
            record["stratum"] = case["stratum"]
            record["input_sha256"] = input_hash(case)
            record["model"] = MODEL
            record["base_url"] = BASE_URL
            record["elapsed_sec"] = round(dt, 1)
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            fh.flush()
            flag = "DEGRADED" if record.get("degraded") else "ok      "
            print(
                f"[{i:2d}/{len(selected)}] {flag} {dt:5.1f}s {bid}",
                file=sys.stderr,
            )

    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
