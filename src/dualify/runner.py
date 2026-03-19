import argparse
import ast
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from dualify.discovery import discover_python_cases, discover_repo_cases
from dualify.fallbacks import get_fallback_extraction
from dualify.io_utils import write_json
from dualify.ollama_client import OllamaClient
from dualify.phases.p01_spec_to_logic import extract_spec_logic
from dualify.phases.p02_code_to_logic import extract_code_logic
from dualify.phases.p03_smt_checking import CaseSpec, check_equivalence, is_parseable
from dualify.phases.p04_action_planning import (
    build_action_plan,
    choose_action_interactively,
    print_comparison_report,
)
from dualify.phases.p05_action_execution import execute_action
from dualify.types import BenchmarkCase, SmtResult

ROOT = Path(__file__).resolve().parents[2]

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


def _run_cases(client: OllamaClient, cases: list[BenchmarkCase]) -> tuple[list[dict], int, int]:
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

        action_plan_payload = build_action_plan(
            client=client,
            benchmark_id=benchmark_id,
            signature=signature,
            informal_spec=informal_spec,
            smt_result=smt_result,
        )

        case_results.append(
            {
                "benchmark_id": benchmark_id,
                "file": case.file,
                "signature": signature,
                "informal_spec": informal_spec,
                "extra_context": extra_context,
                "spec_to_logic": {**asdict(spec_logic), "used_fallback": used_spec_fallback},
                "code_to_logic": {**asdict(code_logic), "used_fallback": used_code_fallback},
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
        },
        "results": case_results,
    }
    if extra_fields:
        report.update(extra_fields)
    return report


def run_experiment(model: str, base_url: str, benchmark_name: str = "synthetic") -> dict:
    benchmark_dir = ROOT / "benchmark" / benchmark_name
    if not benchmark_dir.exists():
        raise FileNotFoundError(f"Benchmark directory not found: {benchmark_dir}")
    cases = discover_python_cases(benchmark_dir=benchmark_dir, root_dir=ROOT)

    client = OllamaClient(model=model, base_url=base_url)
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
) -> dict:
    target_repo = Path(repo_path).expanduser().resolve()
    if not target_repo.exists() or not target_repo.is_dir():
        raise FileNotFoundError(f"Repository path not found: {target_repo}")

    client = OllamaClient(model=model, base_url=base_url)
    client.healthcheck()
    cases = _order_cases_by_execution(discover_repo_cases(target_repo))
    if not cases:
        raise ValueError(
            "No supported functions discovered. "
            "Add type-annotated functions with int/bool/float signatures."
        )

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
) -> dict:
    target_repo = Path(repo_path).expanduser().resolve()
    if not target_repo.exists() or not target_repo.is_dir():
        raise FileNotFoundError(f"Repository path not found: {target_repo}")

    client = OllamaClient(model=model, base_url=base_url)
    client.healthcheck()
    ordered_cases = _order_cases_by_execution(discover_repo_cases(target_repo))
    if not ordered_cases:
        raise ValueError(
            "No supported functions discovered. "
            "Add type-annotated functions with int/bool/float signatures."
        )

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
                signature=case_result["signature"],
                informal_spec=case_result["informal_spec"],
                smt_result=smt_result,
                action_plan=action_plan,
            )

            if smt_result.equivalent:
                print(
                    _label("Status:"),
                    _style("EQUIVALENT", _ANSI_BOLD, _ANSI_GREEN),
                    _style("→ moving to next function", _ANSI_WHITE),
                )
                break

            selection = choose_action_interactively(action_plan)
            if selection == "__quit__":
                stop_all = True
                break
            if selection == "__next__":
                break

            p05_result = execute_action(
                client=client,
                action=selection,
                benchmark_id=case_result["benchmark_id"],
                signature=case_result["signature"],
                informal_spec=case_result["informal_spec"],
                smt_result=smt_result,
                triggered_case=action_plan.get("triggered_case", "UNKNOWN"),
            )
            print("\n" + _style(" p05 action result ", _ANSI_BOLD, _ANSI_WHITE, _ANSI_BG_BLUE))
            print(json.dumps(p05_result, indent=2, ensure_ascii=False))

            followup = input(
                "\n"
                + _style("Command", _ANSI_BOLD, _ANSI_WHITE)
                + ": "
                + _style("[r]", _ANSI_CYAN)
                + " re-run, "
                + _style("[n]", _ANSI_CYAN)
                + " next, "
                + _style("[q]", _ANSI_RED)
                + " quit: "
            ).strip().lower()
            if followup == "q":
                stop_all = True
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
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Dualify full experiment")
    parser.add_argument("--model", default="qwen2.5:3b-instruct")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--benchmark", default="synthetic")
    parser.add_argument("--repo-path", default="")
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--non-interactive", action="store_true")
    args = parser.parse_args()

    if args.repo_path:
        if args.non_interactive:
            report = run_repo_scan(
                model=args.model,
                base_url=args.base_url,
                repo_path=args.repo_path,
                iterations=args.iterations,
            )
        else:
            report = run_repo_cli(
                model=args.model,
                base_url=args.base_url,
                repo_path=args.repo_path,
                iterations=args.iterations,
            )
    else:
        report = run_experiment(
            model=args.model,
            base_url=args.base_url,
            benchmark_name=args.benchmark,
        )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

