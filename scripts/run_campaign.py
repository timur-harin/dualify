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
from dualify.cloud_providers import profile_for_base_url  # noqa: E402
from dualify.io_utils import write_json  # noqa: E402
from dualify.ollama_client import LLMClient, create_llm_client  # noqa: E402
from dualify.runner import run_experiment  # noqa: E402
from dualify.transcript import (  # noqa: E402
    RecordingLLMClient,
    ReplayLLMClient,
    ResumingLLMClient,
)


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


def _maybe_throttle(client: LLMClient, base_url: str, *, no_throttle: bool = False) -> LLMClient:
    if no_throttle:
        print("[campaign] throttling disabled (--no-throttle)", file=sys.stderr)
        return client
    profile = profile_for_base_url(base_url)
    if profile is not None and profile.min_interval_sec > 0:
        print(
            f"[campaign] provider={profile.name} rpm={profile.rpm} "
            f"min_interval={profile.min_interval_sec}s timeout={profile.timeout_sec}s "
            f"retries={profile.max_retries}",
            file=sys.stderr,
        )
        return ThrottledLLMClient(inner=client, min_interval_sec=profile.min_interval_sec)
    return client


def _slug(model: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in model).strip("_")


def _transcript_record_count(path: Path) -> int:
    if not path.is_file():
        return 0
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and "transcript_metadata" not in stripped:
            count += 1
    return count


def _count_degraded_posts(report: dict) -> tuple[int, int]:
    """Return (degraded_ret_ret_count, total_postconditions)."""
    degraded = 0
    total = 0
    for case in report.get("results", []):
        for channel in ("spec_to_logic", "code_to_logic"):
            payload = case.get(channel, {})
            if not payload:
                continue
            total += 1
            post = str(payload.get("postcondition", "")).strip()
            if post in {"ret == ret", "ret==ret"} or payload.get("degraded"):
                degraded += 1
    return degraded, total


def _expected_min_llm_calls(n_cases: int) -> int:
    # Each case needs at least spec + code extraction; repairs add more.
    return max(2, n_cases * 2)


def _validate_run(
    report: dict,
    transcript_path: Path,
    *,
    partial_ok: bool,
) -> tuple[bool, str]:
    n_cases = len(report.get("results", []))
    if n_cases == 0:
        return False, "report has zero cases"

    llm_calls = _transcript_record_count(transcript_path)
    min_calls = _expected_min_llm_calls(n_cases)
    if llm_calls < min_calls:
        msg = f"transcript has {llm_calls} LLM call(s), need >= {min_calls} for {n_cases} cases"
        if partial_ok and llm_calls > 0:
            return False, f"partial: {msg} (resume to continue)"
        return False, msg

    degraded, total = _count_degraded_posts(report)
    if total and degraded / total > 0.85:
        msg = f"too many degraded extractions ({degraded}/{total} channels are ret==ret/degraded)"
        if partial_ok and llm_calls < min_calls:
            return False, f"partial: {msg}"
        return False, msg

    return True, f"ok: {llm_calls} LLM calls, {degraded}/{total} degraded channels"


def _fresh_run_dir(run_dir: Path, benchmark: str) -> None:
    for pattern in ("transcript.jsonl", f"{benchmark}_*.json"):
        for path in run_dir.glob(pattern):
            path.unlink()


def _api_key_from_env() -> str:
    for name in (
        "DUALIFY_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "SAMBANOVA_API_KEY",
    ):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default=_api_key_from_env())
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
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Continue from existing run_NN/transcript.jsonl (cached calls + live append).",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Delete existing transcript and report JSON in each run dir before starting.",
    )
    parser.add_argument(
        "--no-throttle",
        action="store_true",
        help="Disable inter-call pacing (paid OpenRouter; use when credits allow full RPM).",
    )
    parser.add_argument(
        "--partial-ok",
        action="store_true",
        help="Exit 0 when transcript incomplete but growing (multi-day RPD limits).",
    )
    args = parser.parse_args()

    if not args.api_key and not args.replay_dir:
        print("[campaign] error: no API key in env", file=sys.stderr)
        sys.exit(2)

    label = args.label or _slug(args.model)
    out_dir = ROOT / "results" / "campaigns" / f"{args.benchmark}__{label}"
    out_dir.mkdir(parents=True, exist_ok=True)

    reports: list[dict] = []
    for i in range(1, args.runs + 1):
        run_dir = out_dir / f"run_{i:02d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        transcript = run_dir / "transcript.jsonl"

        if args.fresh:
            _fresh_run_dir(run_dir, args.benchmark)

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
            live = _maybe_throttle(live, args.base_url, no_throttle=args.no_throttle)
            cached = _transcript_record_count(transcript) if args.resume else 0
            if args.resume and cached > 0:
                client = ResumingLLMClient.from_path(inner=live, path=transcript.resolve())
                print(
                    f"[campaign] resume: {cached} cached LLM call(s) in {transcript.name}",
                    file=sys.stderr,
                )
            else:
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
        if isinstance(client, RecordingLLMClient | ResumingLLMClient):
            client.close()
        reports.append(report)
        cc = report["summary"]["cross_check"]
        print(
            f"[campaign] run {i}: genuine_equiv={cc['genuine_equivalent_cases']} "
            f"low_conf={cc['low_confidence_cases']} unknown={cc['solver_unknown_cases']} "
            f"parse_err={cc['parse_error_cases']}",
            file=sys.stderr,
        )
        ok, detail = _validate_run(report, transcript, partial_ok=args.partial_ok)
        llm_calls = _transcript_record_count(transcript)
        print(
            f"[campaign] run {i} validation: {'PASS' if ok else 'FAIL'} — {detail} "
            f"(transcript={llm_calls} calls)",
            file=sys.stderr,
        )
        if not ok:
            if args.partial_ok and detail.startswith("partial:"):
                print(
                    "[campaign] partial run saved; re-invoke with --resume to continue",
                    file=sys.stderr,
                )
                sys.exit(0)
            print(f"[campaign] aborting: {detail}", file=sys.stderr)
            sys.exit(1)

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
