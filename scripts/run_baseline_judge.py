#!/usr/bin/env python3
"""LLM-as-judge / no-SMT baseline for spec-code inconsistency detection.

This is the baseline Dualify is meant to beat on *trustworthiness*: a single
LLM call is shown the informal spec and the implementation and asked, directly,
whether they are consistent -- no formula extraction, no Z3. We score it as an
inconsistency detector against ground-truth labels and contrast it with
Dualify's Z3 cross-check on the same cases.

Ground truth: the two bug-injected gold records (`count_flips`, `next_departure`
under an `incorrect` path) are the should-DISAGREE positives; the other 38
correct implementations should AGREE with their spec.

Detection framing (positive class = "inconsistent / disagree"):
  TP  predicted disagree, truly buggy        (bug caught)
  FN  predicted agree,    truly buggy        (bug missed  -> false agreement)
  FP  predicted disagree, truly correct      (false alarm)
  TN  predicted agree,    truly correct
  false_agreement_rate = FN / (#buggy)

Usage:
    PYTHONPATH=src python scripts/run_baseline_judge.py \
        --provider openai --base-url http://10.100.30.241:8802 --api-key API_KEY \
        --model "Qwen/Qwen3-Coder-Next-FP8" --runs 7 --label qwen_local \
        --dualify-campaign results/campaigns/lifted_auto_eval__qwen_local
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dualify.aggregate import _stats  # noqa: E402
from dualify.discovery import discover_python_cases  # noqa: E402
from dualify.io_utils import write_json  # noqa: E402
from dualify.ollama_client import create_llm_client  # noqa: E402
from dualify.transcript import RecordingLLMClient, ReplayLLMClient  # noqa: E402
from dualify.types import BenchmarkCase  # noqa: E402

JUDGE_PROMPT = """You are auditing whether a Python function's implementation is \
consistent with its informal specification.

Decide: does the implementation satisfy the specification for all valid inputs?
Answer ONLY with strict JSON:
{{"consistent": true_or_false, "confidence": "low|medium|high", "reason": "one sentence"}}

Informal specification:
{spec}

Signature: {signature}

Implementation:
{code}
"""


def _is_buggy(case: BenchmarkCase) -> bool:
    return "incorrect" in case.file or "incorrect" in case.benchmark_id


def _judge(client: object, case: BenchmarkCase) -> bool:
    prompt = JUDGE_PROMPT.format(
        spec=case.informal_spec, signature=case.signature, code=case.function_source
    )
    payload = client.generate_json(prompt, temperature=0.0)  # type: ignore[attr-defined]
    if not isinstance(payload, dict):
        return True  # no verdict -> treat as "agree" (a missed bug)
    return bool(payload.get("consistent", True))


def _confusion(predicted_agree: dict[str, bool], buggy: dict[str, bool]) -> dict[str, float]:
    tp = fp = tn = fn = 0
    for bid, is_buggy in buggy.items():
        agree = predicted_agree.get(bid, True)
        if is_buggy and not agree:
            tp += 1
        elif is_buggy and agree:
            fn += 1
        elif (not is_buggy) and (not agree):
            fp += 1
        else:
            tn += 1
    n_buggy = sum(1 for v in buggy.values() if v)
    n_correct = len(buggy) - n_buggy
    return {
        "tp": tp,
        "fn": fn,
        "fp": fp,
        "tn": tn,
        "false_agreement_rate": (fn / n_buggy) if n_buggy else 0.0,
        "false_alarm_rate": (fp / n_correct) if n_correct else 0.0,
        "accuracy": (tp + tn) / len(buggy) if buggy else 0.0,
    }


def _dualify_predictions(campaign_dir: Path, benchmark: str) -> list[dict[str, bool]]:
    """Per-run map: benchmark_key -> agree (genuine cross-check equivalent)."""
    preds: list[dict[str, bool]] = []
    for run_dir in sorted(campaign_dir.glob("run_*")):
        reports = list(run_dir.glob(f"{benchmark}_*.json"))
        if not reports:
            continue
        data = json.loads(reports[0].read_text())
        run_pred: dict[str, bool] = {}
        for case in data.get("results", []):
            key = f"{case.get('file')}::{case.get('benchmark_id')}"
            run_pred[key] = bool(case.get("smt_checking", {}).get("equivalent"))
        preds.append(run_pred)
    return preds


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default=os.environ.get("DUALIFY_API_KEY", ""))
    parser.add_argument("--model", required=True)
    parser.add_argument("--benchmark", default="lifted_auto_eval")
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--label", default="judge")
    parser.add_argument("--dualify-campaign", default="")
    parser.add_argument("--replay-dir", default="")
    args = parser.parse_args()

    cases = discover_python_cases(ROOT / "benchmark" / args.benchmark, ROOT)
    buggy = {f"{c.file}::{c.benchmark_id}": _is_buggy(c) for c in cases}
    out_dir = ROOT / "results" / "baselines" / f"{args.benchmark}__{args.label}"
    out_dir.mkdir(parents=True, exist_ok=True)

    judge_confusions: list[dict[str, float]] = []
    per_run_predictions: list[dict[str, bool]] = []
    for i in range(1, args.runs + 1):
        run_dir = out_dir / f"run_{i:02d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        transcript = run_dir / "transcript.jsonl"
        if args.replay_dir:
            client: object = ReplayLLMClient.from_path(
                (Path(args.replay_dir) / f"run_{i:02d}" / "transcript.jsonl").resolve()
            )
        else:
            live = create_llm_client(
                provider=args.provider,
                model=args.model,
                base_url=args.base_url,
                api_key=args.api_key,
            )
            client = RecordingLLMClient(
                inner=live,
                transcript_path=transcript,
                model=args.model,
                base_url=args.base_url,
                provider=args.provider,
            )
        predicted_agree = {f"{c.file}::{c.benchmark_id}": _judge(client, c) for c in cases}
        if isinstance(client, RecordingLLMClient):
            client.close()
        per_run_predictions.append(predicted_agree)
        conf = _confusion(predicted_agree, buggy)
        judge_confusions.append(conf)
        print(
            f"[judge] run {i}: caught={conf['tp']}/{sum(buggy.values())} "
            f"false_agree_rate={conf['false_agreement_rate']:.2f} "
            f"false_alarm_rate={conf['false_alarm_rate']:.2f}",
            file=sys.stderr,
        )

    result: dict[str, object] = {
        "label": args.label,
        "model": args.model,
        "benchmark": args.benchmark,
        "n_runs": args.runs,
        "n_buggy": sum(buggy.values()),
        "n_correct": len(buggy) - sum(buggy.values()),
        "judge": {
            "per_run": judge_confusions,
            "false_agreement_rate": _stats([c["false_agreement_rate"] for c in judge_confusions]),
            "false_alarm_rate": _stats([c["false_alarm_rate"] for c in judge_confusions]),
            "accuracy": _stats([c["accuracy"] for c in judge_confusions]),
        },
    }

    if args.dualify_campaign:
        preds = _dualify_predictions(Path(args.dualify_campaign), args.benchmark)
        dconf = [_confusion(p, buggy) for p in preds]
        result["dualify"] = {
            "per_run": dconf,
            "false_agreement_rate": _stats([c["false_agreement_rate"] for c in dconf]),
            "false_alarm_rate": _stats([c["false_alarm_rate"] for c in dconf]),
            "accuracy": _stats([c["accuracy"] for c in dconf]),
        }

    write_json(out_dir / "summary.json", result)
    print(json.dumps({k: result[k] for k in ("judge",) if k in result}, indent=2)[:1500])
    print(f"[judge] wrote {out_dir / 'summary.json'}", file=sys.stderr)


if __name__ == "__main__":
    main()
