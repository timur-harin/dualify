from dualify.ollama_client import OllamaClient
from dualify.types import SmtResult

ACTION_CATALOG = [
    "refine_spec",
    "add_property_to_ignore_list",
    "relax_constraints_in_implementation",
    "fix_implementation",
    "extend_implementation_or_feature_request",
    "relax_spec_maybe_ignore",
    "add_test_case",
    "no_test_case",
]


def _resolve_case_and_actions(smt_result: SmtResult) -> tuple[str, list[str]]:
    diagnostics = smt_result.diagnostics or {}
    reason = smt_result.reason

    if reason == "case_pre_code":
        return (
            "PRE_CODE",
            [
                "refine_spec",
                "add_property_to_ignore_list",
                "relax_constraints_in_implementation",
                "add_test_case",
            ],
        )
    if reason == "case_pre_spec":
        return (
            "PRE_SPEC",
            [
                "fix_implementation",
                "refine_spec",
                "add_test_case",
            ],
        )
    if reason == "case_post_code":
        return (
            "POST_CODE",
            [
                "refine_spec",
                "add_property_to_ignore_list",
                "extend_implementation_or_feature_request",
                "no_test_case",
            ],
        )
    if reason == "case_post_spec":
        return (
            "POST_SPEC",
            [
                "relax_spec_maybe_ignore",
                "fix_implementation",
                "add_test_case",
            ],
        )
    if reason == "equivalent_no_mismatch" or smt_result.equivalent:
        return (
            "EQUIVALENT",
            [],
        )

    if diagnostics.get("pre_mismatch") is True:
        spec_implies_code = diagnostics.get("pre_spec_implies_pre_code")
        if spec_implies_code is False:
            return (
                "PRE_CODE",
                [
                    "refine_spec",
                    "add_property_to_ignore_list",
                    "relax_constraints_in_implementation",
                    "add_test_case",
                ],
            )
        return (
            "PRE_SPEC",
            [
                "fix_implementation",
                "refine_spec",
                "add_test_case",
            ],
        )
    if diagnostics.get("post_mismatch_on_common_pre") is True:
        spec_post_implies_code = diagnostics.get("post_spec_implies_post_code_on_common_pre")
        if spec_post_implies_code is False:
            return (
                "POST_CODE",
                [
                    "refine_spec",
                    "add_property_to_ignore_list",
                    "extend_implementation_or_feature_request",
                    "no_test_case",
                ],
            )
        return (
            "POST_SPEC",
            [
                "relax_spec_maybe_ignore",
                "fix_implementation",
                "add_test_case",
            ],
        )

    return (
        "UNKNOWN",
        [
            "add_test_case",
        ],
    )


def build_action_plan(
    client: OllamaClient,
    benchmark_id: str,
    signature: str,
    informal_spec: str,
    smt_result: SmtResult,
) -> dict:
    diagnostics = smt_result.diagnostics or {}
    triggered_case, baseline_actions = _resolve_case_and_actions(smt_result)
    prompt = f"""
You are an action planner for Dualify verification results.

Variables:
- pre_spec = And(c1..cn)
- pre_code = And(c1'..cm')
- common_pre = And(pre_spec, pre_code)
- post_spec = P
- post_code = P'

Use this scheme:
1) If precondition mismatch is true:
   - if pre_spec_implies_pre_code is false:
     triggered_case = PRE_CODE
     actions = [refine_spec, add_property_to_ignore_list,
                relax_constraints_in_implementation, add_test_case]
   - else:
     triggered_case = PRE_SPEC
     actions = [fix_implementation, refine_spec, add_test_case]
2) If precondition mismatch is false and postcondition mismatch exists:
   - if post_spec_implies_post_code_on_common_pre is false:
     triggered_case = POST_CODE
     actions = [refine_spec, add_property_to_ignore_list,
                extend_implementation_or_feature_request, no_test_case]
   - else:
     triggered_case = POST_SPEC
     actions = [relax_spec_maybe_ignore, fix_implementation, add_test_case]
3) If equivalent:
   triggered_case = EQUIVALENT
   actions = []

Output strict JSON:
{{
  "benchmark_id": "{benchmark_id}",
  "recommended_actions": ["subset of baseline actions, keep order by priority"],
  "summary": "short explanation based on diagnostics"
}}

Allowed actions:
{ACTION_CATALOG}

Baseline case (already computed deterministically):
- triggered_case: {triggered_case}
- baseline_actions: {baseline_actions}

Input:
- Signature: {signature}
- Informal spec: {informal_spec}
- SMT reason: {smt_result.reason}
- SMT equivalent: {smt_result.equivalent}
- Diagnostics: {diagnostics}
"""
    payload = client.generate_json(prompt, temperature=0.0)
    if not isinstance(payload, dict):
        payload = {}
    recommended = payload.get("recommended_actions", baseline_actions)
    if not isinstance(recommended, list):
        recommended = baseline_actions
    clean_recommended = [
        action for action in recommended if isinstance(action, str) and action in baseline_actions
    ]
    deduped_recommended: list[str] = []
    for action in clean_recommended:
        if action not in deduped_recommended:
            deduped_recommended.append(action)
    clean_recommended = deduped_recommended
    if not clean_recommended:
        clean_recommended = baseline_actions
    summary = payload.get("summary", "")
    if not isinstance(summary, str):
        summary = ""

    return {
        "benchmark_id": benchmark_id,
        "triggered_case": triggered_case,
        "baseline_actions": baseline_actions,
        "recommended_actions": clean_recommended,
        "summary": summary,
    }

