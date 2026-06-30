#!/usr/bin/env python3
"""Run a Dualify benchmark campaign: N repeated runs + aggregate statistics.

Each run is recorded to its own frozen LLM transcript so the whole campaign is
replayable offline (zero API calls) by reviewers. After the runs complete, the
script writes ``aggregate.json`` (mean/median/std/min/max per metric) and a
cross-run stability summary.

Example (local Qwen, 7 runs over the gold eval set):

    PYTHONPATH=src python scripts/run_campaign.py \
        --provider openai --base-url http://10.100.30.241:8802 \
        --api-key API_KEY --model "Qwen/Qwen3-Coder-Next-FP8" \
        --benchmark lifted_auto_eval --runs 7 --label qwen_local
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dualify.aggregate import aggregate_runs, stable_cases  # noqa: E402
from dualify.io_utils import write_json  # noqa: E402
from dualify.ollama_client import LLMClient, create_llm_client  # noqa: E402
from dualify.runner import run_experiment  # noqa: E402
from dualify.transcript import RecordingLLMClient, ReplayLLMClient  # noqa: E402


@dataclass
class ThrottledLLMClient:
    """Rate-limit cloud provider calls so benchmark campaigns finish reliably."""

    inner: LLMClient
    min_interval_sec: float = 3.0
    _last_call_at: float = field(default=0.0, init=False)

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        elapsed = time.monotonic() - self._last_call_at
        if elapsed < self.min_interval_sec:
            time.sleep(self.min_interval_sec - elapsed)
        payload = self.inner.generate_json(prompt, temperature=temperature)
        self._last_call_at = time.monotonic()
        return payload

    def healthcheck(self) -> None:
        self.inner.healthcheck()


def _maybe_throttle(client: LLMClient, base_url: str) -> LLMClient:
    host = base_url.lower()
    if "groq.com" in host:
        return ThrottledLLMClient(inner=client, min_interval_sec=2.0)
    if "sambanova.ai" in host:
        return ThrottledLLMClient(inner=client, min_interval_sec=3.0)
    return client


def _slug(model: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in model).strip("_")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default=os.environ.get("DUALIFY_API_KEY", ""))
    parser.add_argument("--model", required=True)
    parser.add_argument("--benchmark", default="lifted_auto_eval")
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--label", default="")
    parser.add_argument("--target", action="append", default=[], help="Benchmark id/name filter")
    parser.add_argument("--target-regex", action="append", default=[], help="Benchmark id regex")
    parser.add_argument("--max-cases", type=int, default=None, help="Deterministic prefix after filters")
    parser.add_argument(
        "--replay-dir",
        default="",
        help="If set, replay each run from <dir>/run_NN/transcript.jsonl instead of the live API.",
    )
    args = parser.parse_args()

    label = args.label or _slug(args.model)
    out_dir = ROOT / "results" / "campaigns" / f"{args.benchmark}__{label}"
    out_dir.mkdir(parents=True, exist_ok=True)

    reports: list[dict] = []
    for i in range(1, args.runs + 1):
        run_dir = out_dir / f"run_{i:02d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        transcript = run_dir / "transcript.jsonl"

        if args.replay_dir:
            replay_path = Path(args.replay_dir) / f"run_{i:02d}" / "transcript.jsonl"
            client = ReplayLLMClient.from_path(replay_path.resolve())
        else:
            live = create_llm_client(
                provider=args.provider,
                model=args.model,
                base_url=args.base_url,
                api_key=args.api_key,
            )
            live = _maybe_throttle(live, args.base_url)
            client = RecordingLLMClient(
                inner=live,
                transcript_path=transcript,
                model=args.model,
                base_url=args.base_url,
                provider=args.provider,
            )

        print(f"[campaign] run {i}/{args.runs} -> {run_dir}", file=sys.stderr)
        report = run_experiment(
            model=args.model,
            base_url=args.base_url,
            benchmark_name=args.benchmark,
            provider=args.provider,
            api_key=args.api_key,
            client_override=client,
            output_dir=run_dir,
            targets=args.target,
            target_regexes=args.target_regex,
            max_cases=args.max_cases,
        )
        if isinstance(client, RecordingLLMClient):
            client.close()
        reports.append(report)
        cc = report["summary"]["cross_check"]
        print(
            f"[campaign] run {i}: genuine_equiv={cc['genuine_equivalent_cases']} "
            f"low_conf={cc['low_confidence_cases']} unknown={cc['solver_unknown_cases']} "
            f"parse_err={cc['parse_error_cases']}",
            file=sys.stderr,
        )

    aggregate = {
        "label": label,
        "model": args.model,
        "benchmark": args.benchmark,
        "n_runs": args.runs,
        "selection": {
            "targets": args.target,
            "target_regexes": args.target_regex,
            "max_cases": args.max_cases,
        },
        "aggregate": aggregate_runs(reports),
        "stability_genuine_equivalent": stable_cases(reports, "equivalent"),
    }
    write_json(out_dir / "aggregate.json", aggregate)
    print(json.dumps(aggregate["aggregate"]["cross_check"], indent=2))
    print(f"[campaign] wrote {out_dir / 'aggregate.json'}", file=sys.stderr)


if __name__ == "__main__":
    main()
