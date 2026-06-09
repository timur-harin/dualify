import argparse
import ast
import fnmatch
import json
import os
import re
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from dualify.discovery import discover_python_cases, discover_repo_cases
from dualify.fallbacks import get_fallback_extraction
from dualify.formula_parser import normalize_formula
from dualify.health import summarize_extraction, summarize_run
from dualify.io_utils import write_json
from dualify.ollama_client import LLMClient, create_llm_client
from dualify.phases.p01_spec_to_logic import extract_spec_logic
from dualify.phases.p02_code_to_logic import extract_code_logic
from dualify.phases.p03_smt_checking import CaseSpec, check_equivalence, is_parseable
from dualify.phases.p04_action_planning import (
    build_action_plan,
    choose_action_interactively,
    print_comparison_report,
)
from dualify.phases.p05_action_execution import execute_action
from dualify.transcript import RecordingLLMClient, ReplayLLMClient, ResumingLLMClient
from dualify.types import BenchmarkCase, SmtResult

ROOT = Path(__file__).resolve().parents[2]

_DOTENV_PATH = ROOT / ".env"
try:
    from dotenv import load_dotenv

    load_dotenv(_DOTENV_PATH)
except ImportError:
    # python-dotenv is a declared dependency in pyproject.toml. If the
    # import fails the env is broken (probably an incomplete `poetry
    # install`). Silently ignoring used to mask a real misconfiguration
    # where users edited .env but their values never reached the runner.
    if _DOTENV_PATH.exists():
        print(
            f"Warning: {_DOTENV_PATH} exists but python-dotenv is not installed; "
            "values were not loaded. Run `poetry install` to fix.",
            file=sys.stderr,
        )

_ANSI_RESET = "\033[0m"
_ANSI_BOLD = "\033[1m"
_ANSI_RED = "\033[31m"
_ANSI_GREEN = "\033[32m"
_ANSI_YELLOW = "\033[33m"
_ANSI_CYAN = "\033[36m"
_ANSI_WHITE = "\033[97m"
_ANSI_BG_BLUE = "\033[44m"


def _style(text: str, *codes: str) -> str:
    return f"{''.join(codes)}{text}{_ANSI_RESET}"


def _label(text: str) -> str:
    return _style(text, _ANSI_BOLD, _ANSI_WHITE)


def _normalize_extraction(case_spec: CaseSpec, post: str, extraction: dict) -> dict:
    normalized = dict(extraction)
    if "ret" not in post and case_spec.return_type == "bool":
        normalized["postcondition"] = f"ret == ({post})"
    return normalized


def _is_weak_postcondition(postcondition: str) -> bool:
    normalized = normalize_formula(postcondition).replace(" ", "")
    return normalized in {"ret==ret", "True", "(True)", "(ret==ret)"}


def _utc_timestamp_for_filename() -> str:
    return datetime.now(UTC).strftime("%Y_%m_%d_%H_%M_%S")


def _short_case_name(case: BenchmarkCase) -> str:
    return case.benchmark_id.split("::")[-1]


def _called_names(function_source: str) -> list[str]:
    try:
        module = ast.parse(function_source)
    except SyntaxError:
        return []
    names: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.append(node.func.id)
    seen: set[str] = set()
    deduped: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            deduped.append(name)
    return deduped


def _order_cases_by_execution(cases: list[BenchmarkCase]) -> list[BenchmarkCase]:
    if not cases:
        return []
    id_to_case = {case.benchmark_id: case for case in cases}
    name_to_ids: dict[str, list[str]] = {}
    for case in cases:
        name_to_ids.setdefault(_short_case_name(case), []).append(case.benchmark_id)

    def pick_target(current: BenchmarkCase, called_name: str) -> str | None:
        candidates = name_to_ids.get(called_name, [])
        if not candidates:
            return None
        same_file = [case_id for case_id in candidates if id_to_case[case_id].file == current.file]
        return (same_file or candidates)[0]

    graph: dict[str, list[str]] = {}
    for case in cases:
        targets: list[str] = []
        for called in _called_names(case.function_source):
            target = pick_target(case, called)
            if target and target != case.benchmark_id and target not in targets:
                targets.append(target)
        graph[case.benchmark_id] = targets

    preferred_entries = ("main", "run", "cli", "start")
    sorted_cases = sorted(cases, key=lambda c: c.benchmark_id)
    entry = sorted_cases[0]
    for name in preferred_entries:
        for case in sorted_cases:
            if _short_case_name(case) == name:
                entry = case
                break
        else:
            continue
        break

    ordered: list[BenchmarkCase] = []
    seen: set[str] = set()

    def dfs(case_id: str) -> None:
        if case_id in seen:
            return
        seen.add(case_id)
        ordered.append(id_to_case[case_id])
        for next_id in graph.get(case_id, []):
            dfs(next_id)

    dfs(entry.benchmark_id)
    for case in sorted_cases:
        dfs(case.benchmark_id)
    return ordered


def _matches_target_pattern(benchmark_id: str, pattern: str) -> bool:
    if fnmatch.fnmatch(benchmark_id, pattern):
        return True
    return pattern in benchmark_id


def _filter_cases(
    cases: list[BenchmarkCase],
    *,
    targets: list[str],
    target_regexes: list[str],
) -> list[BenchmarkCase]:
    if not targets and not target_regexes:
        return cases
    compiled_regexes = [re.compile(expr) for expr in target_regexes]
    filtered: list[BenchmarkCase] = []
    for case in cases:
        by_target = any(_matches_target_pattern(case.benchmark_id, pattern) for pattern in targets)
        by_regex = any(regex.search(case.benchmark_id) for regex in compiled_regexes)
        if by_target or by_regex:
            filtered.append(case)
    return filtered


def _print_targets(repo_root: Path, cases: list[BenchmarkCase]) -> None:
    print("\n" + _style(" Discoverable targets ", _ANSI_BOLD, _ANSI_WHITE, _ANSI_BG_BLUE))
    for case in cases:
        abs_location = str((repo_root / case.file).resolve())
        print(
            f"{_style(abs_location, _ANSI_WHITE)}:{_style(str(case.lineno), _ANSI_CYAN)} "
            f"{_style(case.benchmark_id, _ANSI_YELLOW)}"
        )


def _run_cases(client: LLMClient, cases: list[BenchmarkCase]) -> tuple[list[dict], int, int]:
    case_results: list[dict] = []
    fallback_spec_count = 0
    fallback_code_count = 0
    for case in cases:
        benchmark_id = case.benchmark_id
        signature = case.signature
        informal_spec = case.informal_spec
        return_type = case.return_type
        extra_context = case.extra_context
        function_source = case.function_source
        case_spec = CaseSpec(
            benchmark_id=benchmark_id,
            arg_types=case.arg_types,
            return_type=return_type,
        )

        spec_logic = extract_spec_logic(
            client=client,
            benchmark_id=benchmark_id,
            signature=signature,
            informal_spec=informal_spec,
            return_type=return_type,
            extra_context=extra_context,
        )
        spec_logic = type(spec_logic)(
            **_normalize_extraction(case_spec, spec_logic.postcondition, asdict(spec_logic))
        )
        used_spec_fallback = False
        if not is_parseable(case_spec, spec_logic):
            try:
                spec_logic = get_fallback_extraction(benchmark_id)
                used_spec_fallback = True
            except ValueError:
                # Keep original extraction for unknown benchmarks.
                used_spec_fallback = False
        if used_spec_fallback:
            fallback_spec_count += 1

        code_logic = extract_code_logic(
            client=client,
            benchmark_id=benchmark_id,
            signature=signature,
            function_source=function_source,
            return_type=return_type,
            extra_context=extra_context,
        )
        code_logic = type(code_logic)(
            **_normalize_extraction(case_spec, code_logic.postcondition, asdict(code_logic))
        )
        used_code_fallback = False
        if not is_parseable(case_spec, code_logic):
            try:
                code_logic = get_fallback_extraction(benchmark_id)
                used_code_fallback = True
            except ValueError:
                # Keep original extraction for unknown benchmarks.
                used_code_fallback = False
        if used_code_fallback:
            fallback_code_count += 1

        smt_result = check_equivalence(case_spec, spec_logic, code_logic)
        spec_weak = _is_weak_postcondition(spec_logic.postcondition)
        code_weak = _is_weak_postcondition(code_logic.postcondition)
        if spec_weak or code_weak:
            diagnostics = smt_result.diagnostics or {}
            diagnostics["parse_low_confidence"] = True
            diagnostics["spec_weak_postcondition"] = spec_weak
            diagnostics["code_weak_postcondition"] = code_weak
            diagnostics["spec_postcondition"] = spec_logic.postcondition
            diagnostics["code_postcondition"] = code_logic.postcondition
            smt_result = SmtResult(
                benchmark_id=smt_result.benchmark_id,
                equivalent=smt_result.equivalent,
                reason="low_confidence_parse" if smt_result.equivalent else smt_result.reason,
                counterexample=smt_result.counterexample,
                diagnostics=diagnostics,
                well_formedness=smt_result.well_formedness,
            )

        action_plan_payload = build_action_plan(
            client=client,
            benchmark_id=benchmark_id,
            signature=signature,
            informal_spec=informal_spec,
            smt_result=smt_result,
        )

        spec_payload = {**asdict(spec_logic), "used_fallback": used_spec_fallback}
        spec_payload["extractor_health"] = summarize_extraction(spec_payload)
        code_payload = {**asdict(code_logic), "used_fallback": used_code_fallback}
        code_payload["extractor_health"] = summarize_extraction(code_payload)
        case_results.append(
            {
                "benchmark_id": benchmark_id,
                "file": case.file,
                "signature": signature,
                "informal_spec": informal_spec,
                "extra_context": extra_context,
                "spec_to_logic": spec_payload,
                "code_to_logic": code_payload,
                "smt_checking": asdict(smt_result),
                "action_planning": action_plan_payload,
            }
        )
    return case_results, fallback_spec_count, fallback_code_count


def _build_report(
    *,
    run_id_prefix: str,
    mode_name: str,
    model: str,
    base_url: str,
    case_results: list[dict],
    fallback_spec_count: int,
    fallback_code_count: int,
    extra_fields: dict[str, object] | None = None,
) -> dict:
    run_stamp = _utc_timestamp_for_filename()
    equivalent_count = sum(1 for result in case_results if result["smt_checking"]["equivalent"])
    run_health = summarize_run(case_results)
    report: dict[str, object] = {
        "run_id": f"{run_id_prefix}_{run_stamp}",
        "mode": mode_name,
        "ran_at_utc": datetime.now(UTC).isoformat(),
        "model": model,
        "base_url": base_url,
        "summary": {
            "total_cases": len(case_results),
            "equivalent_cases": equivalent_count,
            "non_equivalent_cases": len(case_results) - equivalent_count,
            "spec_fallback_count": fallback_spec_count,
            "code_fallback_count": fallback_code_count,
            **run_health,
        },
        "results": case_results,
    }
    if extra_fields:
        report.update(extra_fields)
    return report


def run_experiment(
    model: str,
    base_url: str,
    benchmark_name: str = "synthetic",
    provider: str = "ollama",
    api_key: str = "",
    client_override: LLMClient | None = None,
) -> dict:
    benchmark_dir = ROOT / "benchmark" / benchmark_name
    if not benchmark_dir.exists():
        raise FileNotFoundError(f"Benchmark directory not found: {benchmark_dir}")
    cases = discover_python_cases(benchmark_dir=benchmark_dir, root_dir=ROOT)

    if client_override is not None:
        client = client_override
    else:
        client = create_llm_client(
            provider=provider, model=model, base_url=base_url, api_key=api_key
        )
    client.healthcheck()
    case_results, fallback_spec_count, fallback_code_count = _run_cases(client, cases)

    report = _build_report(
        run_id_prefix=benchmark_name,
        mode_name="benchmark",
        model=model,
        base_url=base_url,
        case_results=case_results,
        fallback_spec_count=fallback_spec_count,
        fallback_code_count=fallback_code_count,
        extra_fields={"benchmark": benchmark_name},
    )

    run_stamp = report["run_id"].split(f"{benchmark_name}_", maxsplit=1)[1]
    output_path = ROOT / "results" / f"{benchmark_name}_{run_stamp}.json"
    write_json(output_path, report)
    return report


def run_repo_scan(
    model: str,
    base_url: str,
    repo_path: str,
    iterations: int = 1,
    targets: list[str] | None = None,
    target_regexes: list[str] | None = None,
    list_targets: bool = False,
    provider: str = "ollama",
    api_key: str = "",
    client_override: LLMClient | None = None,
) -> dict:
    target_repo = Path(repo_path).expanduser().resolve()
    if not target_repo.exists() or not target_repo.is_dir():
        raise FileNotFoundError(f"Repository path not found: {target_repo}")

    discovered_cases = discover_repo_cases(target_repo)
    if list_targets:
        _print_targets(target_repo, discovered_cases)
        return {"mode": "repo_scan", "repo_path": str(target_repo), "listed_targets": True}
    cases = _order_cases_by_execution(
        _filter_cases(
            discovered_cases,
            targets=targets or [],
            target_regexes=target_regexes or [],
        )
    )
    if not cases:
        raise ValueError("No supported functions discovered. Add type-annotated functions.")
    if client_override is not None:
        client = client_override
    else:
        client = create_llm_client(
            provider=provider, model=model, base_url=base_url, api_key=api_key
        )
    client.healthcheck()

    history: list[dict[str, object]] = []
    previous_inconsistent: set[str] | None = None
    case_results: list[dict] = []
    fallback_spec_count = 0
    fallback_code_count = 0

    for iteration in range(1, max(1, iterations) + 1):
        case_results, fallback_spec_count, fallback_code_count = _run_cases(client, cases)
        inconsistent = {
            result["benchmark_id"]
            for result in case_results
            if not result["smt_checking"]["equivalent"]
        }
        history.append(
            {
                "iteration": iteration,
                "inconsistent_count": len(inconsistent),
                "inconsistent_ids": sorted(inconsistent),
            }
        )
        if previous_inconsistent == inconsistent:
            break
        previous_inconsistent = inconsistent

    report = _build_report(
        run_id_prefix=f"repo_scan_{target_repo.name}",
        mode_name="repo_scan",
        model=model,
        base_url=base_url,
        case_results=case_results,
        fallback_spec_count=fallback_spec_count,
        fallback_code_count=fallback_code_count,
        extra_fields={
            "repo_path": str(target_repo),
            "iterations_requested": max(1, iterations),
            "iterations_executed": len(history),
            "iteration_history": history,
        },
    )

    run_stamp = report["run_id"].split(f"repo_scan_{target_repo.name}_", maxsplit=1)[1]
    output_path = ROOT / "results" / f"repo_scan_{target_repo.name}_{run_stamp}.json"
    write_json(output_path, report)
    return report


def run_repo_cli(
    model: str,
    base_url: str,
    repo_path: str,
    iterations: int = 1,
    targets: list[str] | None = None,
    target_regexes: list[str] | None = None,
    list_targets: bool = False,
    verbose: bool = False,
    provider: str = "ollama",
    api_key: str = "",
    client_override: LLMClient | None = None,
) -> dict:
    target_repo = Path(repo_path).expanduser().resolve()
    if not target_repo.exists() or not target_repo.is_dir():
        raise FileNotFoundError(f"Repository path not found: {target_repo}")

    discovered_cases = discover_repo_cases(target_repo)
    if list_targets:
        _print_targets(target_repo, discovered_cases)
        return {"mode": "repo_cli", "repo_path": str(target_repo), "listed_targets": True}
    ordered_cases = _order_cases_by_execution(
        _filter_cases(
            discovered_cases,
            targets=targets or [],
            target_regexes=target_regexes or [],
        )
    )
    if not ordered_cases:
        raise ValueError("No supported functions discovered. Add type-annotated functions.")
    if client_override is not None:
        client = client_override
    else:
        client = create_llm_client(
            provider=provider, model=model, base_url=base_url, api_key=api_key
        )
    client.healthcheck()

    print("\n" + _style(" Repository scan ", _ANSI_BOLD, _ANSI_WHITE, _ANSI_BG_BLUE))
    print(_label("Repository:"), _style(str(target_repo), _ANSI_WHITE))
    print(_label("Functions discovered:"), _style(str(len(ordered_cases)), _ANSI_CYAN))
    print(
        _label("Execution order starts from:"),
        _style(ordered_cases[0].benchmark_id, _ANSI_YELLOW),
    )

    final_results: list[dict] = []
    fallback_spec_total = 0
    fallback_code_total = 0
    stop_all = False

    for case in ordered_cases:
        rerun_budget = max(1, iterations)
        last_result: dict | None = None
        while rerun_budget > 0:
            case_results, spec_fb, code_fb = _run_cases(client, [case])
            fallback_spec_total += spec_fb
            fallback_code_total += code_fb
            case_result = case_results[0]
            last_result = case_result
            smt_result = SmtResult(**case_result["smt_checking"])
            action_plan = case_result["action_planning"]

            print_comparison_report(
                benchmark_id=case_result["benchmark_id"],
                file_path=str((target_repo / case.file).resolve()),
                lineno=case.lineno,
                signature=case_result["signature"],
                informal_spec=case_result["informal_spec"],
                smt_result=smt_result,
                action_plan=action_plan,
                verbose=verbose,
                spec_logic=case_result.get("spec_to_logic"),
                code_logic=case_result.get("code_to_logic"),
            )

            if smt_result.equivalent:
                print(
                    _label("Status:"),
                    _style("EQUIVALENT", _ANSI_BOLD, _ANSI_GREEN),
                    _style("→ waiting for manual command", _ANSI_WHITE),
                )
            else:
                selection = choose_action_interactively(action_plan)
                if selection == "__details__":
                    print_comparison_report(
                        benchmark_id=case_result["benchmark_id"],
                        file_path=str((target_repo / case.file).resolve()),
                        lineno=case.lineno,
                        signature=case_result["signature"],
                        informal_spec=case_result["informal_spec"],
                        smt_result=smt_result,
                        action_plan=action_plan,
                        verbose=True,
                        spec_logic=case_result.get("spec_to_logic"),
                        code_logic=case_result.get("code_to_logic"),
                    )
                    continue
                if selection == "__quit__":
                    stop_all = True
                    break
                if selection == "__next__":
                    break

                actions = [selection] if isinstance(selection, str) else selection
                for action in actions:
                    p05_result = execute_action(
                        client=client,
                        action=action,
                        benchmark_id=case_result["benchmark_id"],
                        signature=case_result["signature"],
                        informal_spec=case_result["informal_spec"],
                        smt_result=smt_result,
                        triggered_case=action_plan.get("triggered_case", "UNKNOWN"),
                    )
                    print(
                        "\n" + _style(" p05 action result ", _ANSI_BOLD, _ANSI_WHITE, _ANSI_BG_BLUE)
                    )
                    print(json.dumps(p05_result, indent=2, ensure_ascii=False))

            followup = (
                input(
                    "\n"
                    + _style("Command", _ANSI_BOLD, _ANSI_WHITE)
                    + ": "
                    + _style("[Enter]", _ANSI_CYAN)
                    + " next, "
                    + _style("[r]", _ANSI_CYAN)
                    + " re-run, "
                    + _style("[n]", _ANSI_CYAN)
                    + " next, "
                    + _style("[q]", _ANSI_RED)
                    + " quit: "
                )
                .strip()
                .lower()
            )
            if followup == "q":
                stop_all = True
                break
            if followup == "":
                break
            if followup != "r":
                break
            rerun_budget -= 1

        if last_result is not None:
            final_results.append(last_result)
        if stop_all:
            break

    report = _build_report(
        run_id_prefix=f"repo_cli_{target_repo.name}",
        mode_name="repo_cli",
        model=model,
        base_url=base_url,
        case_results=final_results,
        fallback_spec_count=fallback_spec_total,
        fallback_code_count=fallback_code_total,
        extra_fields={
            "repo_path": str(target_repo),
            "iterations_requested_per_function": max(1, iterations),
            "functions_planned": len(ordered_cases),
            "functions_processed": len(final_results),
        },
    )

    run_stamp = report["run_id"].split(f"repo_cli_{target_repo.name}_", maxsplit=1)[1]
    output_path = ROOT / "results" / f"repo_cli_{target_repo.name}_{run_stamp}.json"
    write_json(output_path, report)
    _print_run_health_banner(report.get("summary"))
    return report


def _print_run_health_banner(summary: object) -> None:
    if not isinstance(summary, dict):
        return
    print("\n" + _style(" Run health ", _ANSI_BOLD, _ANSI_WHITE, _ANSI_BG_BLUE))
    print(
        _label("Cases:"),
        _style(
            f"total={summary.get('total_cases', 0)}  "
            f"equivalent={summary.get('equivalent_cases', 0)}  "
            f"non_equivalent={summary.get('non_equivalent_cases', 0)}",
            _ANSI_WHITE,
        ),
    )
    extractor = summary.get("extractor_health")
    if isinstance(extractor, dict):
        for side in ("spec", "code"):
            side_payload = extractor.get(side)
            if not isinstance(side_payload, dict):
                continue
            print(
                _label(f"{side.capitalize()} extractor:"),
                _style(
                    f"degraded={side_payload.get('degraded_count', 0)}  "
                    f"weak={side_payload.get('weak_postcondition_count', 0)}  "
                    f"final_stages={side_payload.get('final_stage_counts', {})}",
                    _ANSI_WHITE,
                ),
            )
        print(
            _label("Joint:"),
            _style(
                f"either_degraded={extractor.get('either_degraded_count', 0)}  "
                f"both_degraded={extractor.get('both_degraded_count', 0)}  "
                f"both_weak={extractor.get('both_weak_postcondition_count', 0)}",
                _ANSI_WHITE,
            ),
        )
    verdicts = summary.get("verdict_distribution")
    if isinstance(verdicts, dict) and verdicts:
        print(_label("Verdicts:"), _style(str(verdicts), _ANSI_WHITE))
    wf = summary.get("well_formedness_distribution")
    if isinstance(wf, dict) and wf:
        print(_label("Well-formedness:"), _style(str(wf), _ANSI_WHITE))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Dualify full experiment")
    parser.add_argument(
        "--model",
        default=os.environ.get("DUALIFY_MODEL", "qwen2.5:3b-instruct"),
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("DUALIFY_BASE_URL", "http://127.0.0.1:11434"),
    )
    parser.add_argument(
        "--provider",
        choices=["ollama", "openai"],
        default=os.environ.get("DUALIFY_PROVIDER", "ollama"),
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("DUALIFY_API_KEY", ""),
        help="Also reads GROQ_API_KEY if set and this flag is empty.",
    )
    parser.add_argument("--benchmark", default="synthetic")
    parser.add_argument("--repo-path", default="")
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--target-regex", action="append", default=[])
    parser.add_argument("--list-targets", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--record-transcript",
        default="",
        help=(
            "Append every LLM call to this JSONL file. Wraps the live provider so the "
            "run still produces real results."
        ),
    )
    parser.add_argument(
        "--replay",
        default="",
        help=(
            "Replay LLM responses from this JSONL transcript instead of calling any "
            "live provider. The model / provider / api-key flags are ignored when "
            "replay is active."
        ),
    )
    parser.add_argument(
        "--resume-transcript",
        default="",
        help=(
            "Serve cached responses from this existing JSONL transcript prefix and "
            "fall through to the live provider for any extra calls (appending them "
            "to the same file). Use this to continue an interrupted recording. "
            "Mutually exclusive with --replay and --record-transcript."
        ),
    )
    args = parser.parse_args()
    api_key = (args.api_key or os.environ.get("GROQ_API_KEY", "")).strip()

    client_override = _build_client_override(args, api_key)

    if args.repo_path:
        if args.non_interactive:
            report = run_repo_scan(
                model=args.model,
                base_url=args.base_url,
                repo_path=args.repo_path,
                iterations=args.iterations,
                targets=args.target,
                target_regexes=args.target_regex,
                list_targets=args.list_targets,
                provider=args.provider,
                api_key=api_key,
                client_override=client_override,
            )
        else:
            report = run_repo_cli(
                model=args.model,
                base_url=args.base_url,
                repo_path=args.repo_path,
                iterations=args.iterations,
                targets=args.target,
                target_regexes=args.target_regex,
                list_targets=args.list_targets,
                verbose=args.verbose,
                provider=args.provider,
                api_key=api_key,
                client_override=client_override,
            )
    else:
        report = run_experiment(
            model=args.model,
            base_url=args.base_url,
            benchmark_name=args.benchmark,
            provider=args.provider,
            api_key=api_key,
            client_override=client_override,
        )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if isinstance(client_override, RecordingLLMClient | ResumingLLMClient):
        client_override.close()


def _build_client_override(args: argparse.Namespace, api_key: str) -> LLMClient | None:
    """Construct the LLM client from --replay / --record-transcript / --resume-transcript.

    Returns None when none are given; the run_* functions then build
    a live client from --provider / --model / --base-url / --api-key.
    """
    replay_path = (args.replay or "").strip()
    record_path = (args.record_transcript or "").strip()
    resume_path = (getattr(args, "resume_transcript", "") or "").strip()
    chosen = [
        name
        for name, val in (
            ("--replay", replay_path),
            ("--record-transcript", record_path),
            ("--resume-transcript", resume_path),
        )
        if val
    ]
    if len(chosen) > 1:
        raise ValueError(f"{', '.join(chosen)} are mutually exclusive; pick one.")
    if replay_path:
        return ReplayLLMClient.from_path(Path(replay_path).expanduser().resolve())
    if record_path:
        live_client = create_llm_client(
            provider=args.provider,
            model=args.model,
            base_url=args.base_url,
            api_key=api_key,
        )
        return RecordingLLMClient(
            inner=live_client,
            transcript_path=Path(record_path).expanduser().resolve(),
            model=args.model,
            base_url=args.base_url,
            provider=args.provider,
        )
    if resume_path:
        live_client = create_llm_client(
            provider=args.provider,
            model=args.model,
            base_url=args.base_url,
            api_key=api_key,
        )
        return ResumingLLMClient.from_path(
            inner=live_client,
            path=Path(resume_path).expanduser().resolve(),
        )
    return None


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
