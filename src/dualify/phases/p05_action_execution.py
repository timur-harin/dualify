"""p05 Action Execution.

This phase executes one selected action from p04 using dedicated prompts.
"""

from typing import Final

from dualify.ollama_client import OllamaClient
from dualify.types import SmtResult

ACTION_PROMPTS: Final[dict[str, str]] = {
    "refine_spec": (
        "You are refining an informal specification to better match implementation behavior.\n"
        "Output strict JSON with keys:\n"
        "{\n"
        '  "updated_spec": "concise refined specification",\n'
        '  "rationale": "short reason",\n'
        '  "next_step": "single practical next step"\n'
        "}\n"
        "Focus on clarifying preconditions/postconditions from diagnostics."
    ),
    "add_property_to_ignore_list": (
        "You are deciding if a detected mismatch can be ignored safely.\n"
        "Output strict JSON with keys:\n"
        "{\n"
        '  "ignore_candidate": "property or formula to ignore",\n'
        '  "risk": "low|medium|high",\n'
        '  "guardrail": "condition when ignore is acceptable"\n'
        "}\n"
        "Be conservative and explicit about risk."
    ),
    "relax_constraints_in_implementation": (
        "You are proposing implementation precondition relaxation.\n"
        "Output strict JSON with keys:\n"
        "{\n"
        '  "change_plan": ["step1", "step2"],\n'
        '  "expected_effect": "how preconditions become wider",\n'
        '  "test_to_add": "single regression test idea"\n'
        "}\n"
        "Only propose minimal safe changes."
    ),
    "fix_implementation": (
        "You are proposing a concrete implementation fix.\n"
        "Output strict JSON with keys:\n"
        "{\n"
        '  "bug_summary": "short bug statement",\n'
        '  "fix_plan": ["step1", "step2"],\n'
        '  "test_to_add": "single test case idea"\n'
        "}\n"
        "Align code semantics to specification and diagnostics."
    ),
    "extend_implementation_or_feature_request": (
        "You are proposing feature extension or explicit limitation.\n"
        "Output strict JSON with keys:\n"
        "{\n"
        '  "proposal": "extend implementation or document limitation",\n'
        '  "impact": "who/what is affected",\n'
        '  "decision_data": "what evidence to gather"\n'
        "}\n"
        "Keep proposal practical and scoped."
    ),
    "relax_spec_maybe_ignore": (
        "You are evaluating whether spec is too strict and can be relaxed.\n"
        "Output strict JSON with keys:\n"
        "{\n"
        '  "relaxed_spec": "proposed weaker spec",\n'
        '  "tradeoff": "what guarantee is lost",\n'
        '  "acceptance_rule": "when this relaxation is acceptable"\n'
        "}\n"
        "Avoid over-relaxation."
    ),
    "add_test_case": (
        "You are writing a targeted test recommendation from mismatch evidence.\n"
        "Output strict JSON with keys:\n"
        "{\n"
        '  "test_name": "short test name",\n'
        '  "inputs": {"arg": "value"},\n'
        '  "assertion": "expected property/assertion"\n'
        "}\n"
        "Use SMT counterexample when available."
    ),
    "no_test_case": (
        "You are justifying why no test should be added now.\n"
        "Output strict JSON with keys:\n"
        "{\n"
        '  "reason": "short reason",\n'
        '  "risk": "low|medium|high",\n'
        '  "revisit_trigger": "when to add tests later"\n'
        "}\n"
        "Be strict and risk-aware."
    ),
    "investigate_instrumentation": (
        "You are proposing diagnostics to debug extraction/instrumentation quality.\n"
        "Output strict JSON with keys:\n"
        "{\n"
        '  "suspected_layer": "prompt|parser|normalizer|validator|smt_bridge",\n'
        '  "checks": ["check1", "check2"],\n'
        '  "minimal_change": "single safe instrumentation improvement"\n'
        "}\n"
        "Focus on identifying whether failures come from logic understanding or syntax shaping."
    ),
}


def execute_action(
    client: OllamaClient,
    *,
    action: str,
    benchmark_id: str,
    signature: str,
    informal_spec: str,
    smt_result: SmtResult,
    triggered_case: str,
) -> dict:
    if action not in ACTION_PROMPTS:
        return {
            "benchmark_id": benchmark_id,
            "action": action,
            "status": "unsupported_action",
            "result": {},
        }

    prompt = f"""
You are p05 action executor in Dualify.

{ACTION_PROMPTS[action]}

Context:
- benchmark_id: {benchmark_id}
- signature: {signature}
- informal_spec: {informal_spec}
- triggered_case: {triggered_case}
- smt_reason: {smt_result.reason}
- equivalent: {smt_result.equivalent}
- diagnostics: {smt_result.diagnostics or {}}
- counterexample: {smt_result.counterexample}
"""
    payload = client.generate_json(prompt, temperature=0.0)
    if not isinstance(payload, dict):
        payload = {}

    return {
        "benchmark_id": benchmark_id,
        "action": action,
        "status": "completed",
        "result": payload,
    }
