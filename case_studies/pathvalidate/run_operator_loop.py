#!/usr/bin/env python3
"""Interactive operator loop for pathvalidate case study (LLM-as-judge policy).

Mirrors ``dualify-run`` repo CLI without stdin: prints comparison reports and
records operator decisions in ``operator_log.jsonl``.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from dualify.discovery import discover_repo_cases  # noqa: E402
from dualify.io_utils import write_json  # noqa: E402
from dualify.ollama_client import create_llm_client  # noqa: E402
from dualify.phases.p04_action_planning import (  # noqa: E402
    build_action_plan,
    print_comparison_report,
)
from dualify.phases.p05_action_execution import execute_action  # noqa: E402
from dualify.runner import _filter_cases, _run_cases  # noqa: E402
from dualify.transcript import RecordingLLMClient, ResumingLLMClient  # noqa: E402
from dualify.types import SmtResult  # noqa: E402

CASE_STUDY_DIR = Path(__file__).resolve().parent
REPO_PATH = ROOT / "repos" / "pathvalidate"
TRANSCRIPT = CASE_STUDY_DIR / "transcript.jsonl"
OPERATOR_LOG = CASE_STUDY_DIR / "operator_log.jsonl"
TARGET_REGEX = (
    r"_filename.py::(validate_filename|sanitize_filename|is_valid_filename)"
    r"|_filepath.py::(validate_filepath|sanitize_filepath|is_valid_filepath)"
)


def _judge_select_action(
    *,
    benchmark_id: str,
    smt_result: SmtResult,
    action_plan: dict,
) -> tuple[str, str, list[str]]:
    """LLM-as-judge operator policy (deterministic rules + doc/code heuristics)."""
    actions = [
        item for item in action_plan.get("recommended_actions", []) if isinstance(item, str)
    ]
    reason = smt_result.reason
    triggered = str(action_plan.get("triggered_case", "UNKNOWN"))

    diagnostics = smt_result.diagnostics or {}
    if diagnostics.get("parse_low_confidence") or diagnostics.get("spec_weak_postcondition"):
        return (
            "investigate_instrumentation",
            "Weak/degraded spec extraction; compare docstring to code manually.",
            ["investigate_instrumentation"],
        )

    if smt_result.equivalent:
        return "skip_equivalent", "Channels agree under Z3; no repair needed.", []

    if reason in {"low_confidence_parse", "formula_parse_error", "solver_unknown"}:
        return (
            "investigate_instrumentation",
            f"Unverified ({reason}); defer code change, flag for manual review.",
            ["investigate_instrumentation"],
        )

    # Doc-heavy wrappers: prefer refining spec when code delegates to validators.
    if "sanitize_" in benchmark_id or "is_valid_" in benchmark_id:
        if triggered in {"POST_SPEC", "PRE_SPEC"} and "refine_spec" in actions:
            return (
                "refine_spec",
                "Docstring/README likely incomplete vs implementation; refine spec channel.",
                ["refine_spec"],
            )
        if triggered in {"POST_CODE", "PRE_CODE"} and "fix_implementation" in actions:
            return (
                "fix_implementation",
                "Code channel stricter/looser than documented intent.",
                ["fix_implementation"],
            )

    if triggered in {"POST_SPEC", "PRE_SPEC"} and "refine_spec" in actions:
        return "refine_spec", "Default: spec documents intended behavior.", ["refine_spec"]
    if triggered in {"POST_CODE", "PRE_CODE"} and "add_test_case" in actions:
        return (
            "add_test_case",
            "Capture witness as regression test before doc/code edit.",
            ["add_test_case"],
        )

    chosen = actions[0] if actions else "investigate_instrumentation"
    return chosen, f"Fallback to first recommended action ({triggered}).", [chosen]


def _append_log(entry: dict) -> None:
    OPERATOR_LOG.parent.mkdir(parents=True, exist_ok=True)
    with OPERATOR_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://10.100.30.241:8801")
    parser.add_argument("--api-key", default="API_KEY")
    parser.add_argument("--model", default="Qwen/Qwen3-Coder-Next-FP8")
    parser.add_argument("--run-p05", action="store_true", help="Execute p05 for chosen actions")
    parser.add_argument("--fresh-transcript", action="store_true")
    args = parser.parse_args()

    if args.fresh_transcript and TRANSCRIPT.exists():
        TRANSCRIPT.unlink()

    cases = _filter_cases(
        discover_repo_cases(REPO_PATH),
        targets=[],
        target_regexes=[TARGET_REGEX],
    )
    if not cases:
        raise SystemExit("No cases matched scope regex")

    inner = create_llm_client(
        provider="openai",
        model=args.model,
        base_url=args.base_url,
        api_key=args.api_key,
    )
    inner.healthcheck()
    if TRANSCRIPT.exists() and TRANSCRIPT.stat().st_size > 100 and not args.fresh_transcript:
        client = ResumingLLMClient.from_path(inner, TRANSCRIPT)
    else:
        client = RecordingLLMClient(
            inner=inner,
            transcript_path=TRANSCRIPT,
            model=args.model,
            base_url=args.base_url,
            provider="openai",
        )

    results: list[dict] = []
    print(f"\n=== Pathvalidate operator loop ({len(cases)} functions) ===\n")

    for case in sorted(cases, key=lambda c: c.benchmark_id):
        case_results, _, _ = _run_cases(client, [case])
        case_result = case_results[0]
        smt_result = SmtResult(**case_result["smt_checking"])
        action_plan = case_result["action_planning"]

        print_comparison_report(
            benchmark_id=case_result["benchmark_id"],
            file_path=str((REPO_PATH / case.file).resolve()),
            lineno=case.lineno,
            signature=case_result["signature"],
            informal_spec=case_result["informal_spec"],
            smt_result=smt_result,
            action_plan=action_plan,
            verbose=False,
            spec_logic=case_result.get("spec_to_logic"),
            code_logic=case_result.get("code_to_logic"),
        )

        decision, rationale, selected = _judge_select_action(
            benchmark_id=case_result["benchmark_id"],
            smt_result=smt_result,
            action_plan=action_plan,
        )
        print(f"\n[OPERATOR] decision={decision}")
        print(f"[OPERATOR] rationale: {rationale}")
        if selected:
            print(f"[OPERATOR] actions: {selected}")

        p05_results: list[dict] = []
        if args.run_p05 and selected and decision not in {"skip_equivalent"}:
            for action in selected:
                p05_results.append(
                    execute_action(
                        client=client,
                        action=action,
                        benchmark_id=case_result["benchmark_id"],
                        signature=case_result["signature"],
                        informal_spec=case_result["informal_spec"],
                        smt_result=smt_result,
                        triggered_case=action_plan.get("triggered_case", "UNKNOWN"),
                    )
                )

        log_entry = {
            "ts": datetime.now(UTC).isoformat(),
            "benchmark_id": case_result["benchmark_id"],
            "equivalent": smt_result.equivalent,
            "reason": smt_result.reason,
            "triggered_case": action_plan.get("triggered_case"),
            "operator_decision": decision,
            "rationale": rationale,
            "selected_actions": selected,
            "counterexample": smt_result.counterexample,
            "p05": p05_results,
        }
        _append_log(log_entry)
        results.append(case_result)

    client.close()

    report = {
        "run_id": f"pathvalidate_operator_{datetime.now(UTC).strftime('%Y_%m_%d_%H_%M_%S')}",
        "mode": "operator_loop",
        "repo_path": str(REPO_PATH),
        "model": args.model,
        "base_url": args.base_url,
        "results": results,
    }
    out = CASE_STUDY_DIR / "baseline.json"
    write_json(out, report)
    print(f"\nWrote {out} ({len(results)} cases)")
    print(f"Operator log: {OPERATOR_LOG}")


if __name__ == "__main__":
    main()
