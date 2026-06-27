#!/usr/bin/env python3
"""Drive `dualify-run` interactive CLI with an operator policy.

This script intentionally uses the real interactive CLI flow and sends
choices to stdin based on live output (`Triggered case`, action menu).
"""

from __future__ import annotations

import json
import os
import re
import select
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE_DIR = Path(__file__).resolve().parent
LOG_PATH = CASE_DIR / "interactive_cli.log"
DECISIONS_PATH = CASE_DIR / "interactive_decisions.jsonl"
TRANSCRIPT_PATH = CASE_DIR / "transcript_interactive.jsonl"

ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
TRIGGER_RE = re.compile(r"Triggered case:\s*(.+)$")
DEFAULT_TARGET_RE = (
    r"_filename.py::(validate_filename|sanitize_filename|is_valid_filename)"
    r"|_filepath.py::(validate_filepath|sanitize_filepath|is_valid_filepath)"
    r"|_ltsv.py::(validate_ltsv_label|sanitize_ltsv_label)"
    r"|_symbol.py::(validate_symbol|replace_symbol)"
)


@dataclass
class SessionState:
    benchmark_id: str = ""
    triggered_case: str = "UNKNOWN"
    current_actions: dict[int, str] = field(default_factory=dict)
    decision: str = ""
    selected_action: str = ""
    rationale: str = ""


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def choose_action_by_case(triggered_case: str, actions: dict[int, str]) -> tuple[str, str]:
    if not actions:
        return "n", "No actions suggested; skip function."

    case = triggered_case.strip().upper()
    preferred: list[str]
    if case in {"LOW_CONFIDENCE_PARSE", "VACUOUS_EQUIVALENCE", "SOLVER_UNKNOWN", "UNKNOWN"}:
        return "n", f"{case}: skip and inspect offline."
    if case in {"PRE_SPEC", "POST_SPEC"}:
        preferred = ["refine_spec", "add_test_case", "fix_implementation"]
    elif case in {"PRE_CODE", "POST_CODE"}:
        preferred = ["fix_implementation", "add_test_case", "refine_spec"]
    elif case == "EQUIVALENT":
        return "n", "Equivalent; skip."
    else:
        preferred = ["add_test_case", "refine_spec", "fix_implementation"]

    for name in preferred:
        for idx, action in actions.items():
            if action == name:
                return str(idx), f"{case}: picked `{name}`."
    return "a", f"{case}: fallback to all recommended."


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target-regex",
        default=DEFAULT_TARGET_RE,
        help="Regex passed to dualify-run --target-regex",
    )
    parser.add_argument("--base-url", default="http://10.100.30.241:8801")
    parser.add_argument("--api-key", default="API_KEY")
    parser.add_argument("--model", default="Qwen/Qwen3-Coder-Next-FP8")
    args = parser.parse_args()

    if TRANSCRIPT_PATH.exists():
        TRANSCRIPT_PATH.unlink()
    if DECISIONS_PATH.exists():
        DECISIONS_PATH.unlink()

    env = os.environ.copy()
    env.update(
        {
            "PYTHONUNBUFFERED": "1",
            "DUALIFY_PROVIDER": "openai",
            "DUALIFY_BASE_URL": args.base_url,
            "DUALIFY_MODEL": args.model,
            "DUALIFY_API_KEY": args.api_key,
        }
    )

    cmd = [
        "poetry",
        "run",
        "dualify-run",
        "--provider",
        "openai",
        "--base-url",
        args.base_url,
        "--api-key",
        args.api_key,
        "--model",
        args.model,
        "--repo-path",
        "./repos/pathvalidate",
        "--target-regex",
        args.target_regex,
        "--record-transcript",
        str(TRANSCRIPT_PATH),
    ]

    proc = subprocess.Popen(
        cmd,
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    assert proc.stdout is not None
    assert proc.stdin is not None

    state = SessionState()
    with LOG_PATH.open("w", encoding="utf-8") as log, DECISIONS_PATH.open(
        "a", encoding="utf-8"
    ) as decisions:
        while True:
            if proc.poll() is not None:
                # drain rest
                for line in proc.stdout:
                    log.write(line)
                break

            ready, _, _ = select.select([proc.stdout], [], [], 0.2)
            if not ready:
                continue

            line = proc.stdout.readline()
            if not line:
                continue
            log.write(line)
            log.flush()

            plain = strip_ansi(line).strip()
            if plain.startswith("Target:"):
                state = SessionState(benchmark_id=plain.split("Target:", 1)[1].strip())
                continue
            m = TRIGGER_RE.search(plain)
            if m:
                state.triggered_case = m.group(1).strip()
                continue
            if re.search(r"\[\d+\]\s+\w+", plain):
                idx_m = re.search(r"\[(\d+)\]\s+([a-z_]+)$", plain)
                if idx_m:
                    state.current_actions[int(idx_m.group(1))] = idx_m.group(2)
                continue
            if plain.startswith("Select action:"):
                choice, rationale = choose_action_by_case(
                    state.triggered_case, state.current_actions
                )
                state.decision = "select_action"
                state.selected_action = choice
                state.rationale = rationale
                proc.stdin.write(choice + "\n")
                proc.stdin.flush()
                continue
            if plain.startswith("Select command:"):
                # menu without actions
                state.decision = "select_command"
                state.selected_action = "n"
                state.rationale = "No menu actions; next."
                proc.stdin.write("n\n")
                proc.stdin.flush()
                continue
            if plain.startswith("Command:"):
                # finalize per-function decision record
                payload = {
                    "ts": datetime.now(UTC).isoformat(),
                    "benchmark_id": state.benchmark_id,
                    "triggered_case": state.triggered_case,
                    "actions_menu": state.current_actions,
                    "decision_kind": state.decision,
                    "selected": state.selected_action,
                    "rationale": state.rationale,
                }
                decisions.write(json.dumps(payload, ensure_ascii=False) + "\n")
                decisions.flush()
                proc.stdin.write("\n")  # next function
                proc.stdin.flush()

        rc = proc.wait()
    print(f"interactive cli run finished rc={rc}")
    if rc != 0:
        raise SystemExit(rc)


if __name__ == "__main__":
    main()
