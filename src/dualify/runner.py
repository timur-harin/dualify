import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from dualify.discovery import discover_python_cases
from dualify.fallbacks import get_fallback_extraction
from dualify.io_utils import write_json
from dualify.ollama_client import OllamaClient
from dualify.phases.p01_spec_to_logic import extract_spec_logic
from dualify.phases.p02_code_to_logic import extract_code_logic
from dualify.phases.p03_smt_checking import CaseSpec, check_equivalence, is_parseable
from dualify.phases.p04_action_planning import build_action_plan

ROOT = Path(__file__).resolve().parents[2]


def _normalize_extraction(case_spec: CaseSpec, post: str, extraction: dict) -> dict:
    normalized = dict(extraction)
    if "ret" not in post and case_spec.return_type == "bool":
        normalized["postcondition"] = f"ret == ({post})"
    return normalized


def _utc_timestamp_for_filename() -> str:
    return datetime.now().strftime("%d_%m_%y_%H:%M")


def run_experiment(model: str, base_url: str, benchmark_name: str = "synthetic") -> dict:
    benchmark_dir = ROOT / "benchmark" / benchmark_name
    if not benchmark_dir.exists():
        raise FileNotFoundError(f"Benchmark directory not found: {benchmark_dir}")
    cases = discover_python_cases(benchmark_dir=benchmark_dir, root_dir=ROOT)

    client = OllamaClient(model=model, base_url=base_url)
    client.healthcheck()

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

    ran_at_utc = datetime.now(UTC).isoformat()
    equivalent_count = sum(
        1 for result in case_results if result["smt_checking"]["equivalent"]
    )
    run_stamp = _utc_timestamp_for_filename()
    report = {
        "run_id": f"{benchmark_name}_{run_stamp}",
        "benchmark": benchmark_name,
        "ran_at_utc": ran_at_utc,
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

    output_path = ROOT / "results" / f"{benchmark_name}_{run_stamp}.json"
    write_json(output_path, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Dualify full experiment")
    parser.add_argument("--model", default="qwen2.5:3b-instruct")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--benchmark", default="synthetic")
    args = parser.parse_args()

    report = run_experiment(model=args.model, base_url=args.base_url, benchmark_name=args.benchmark)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

