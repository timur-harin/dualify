import os

from dualify.ollama_client import OllamaClient
from dualify.types import SmtResult

_ANSI_RESET = "\033[0m"
_ANSI_BOLD = "\033[1m"
_ANSI_RED = "\033[31m"
_ANSI_GREEN = "\033[32m"
_ANSI_YELLOW = "\033[33m"
_ANSI_BLUE = "\033[34m"
_ANSI_CYAN = "\033[36m"
_ANSI_WHITE = "\033[97m"
_ANSI_BG_GREEN = "\033[42m"
_ANSI_BG_YELLOW = "\033[43m"
_ANSI_BG_BLUE = "\033[44m"
_ANSI_BG_RED = "\033[41m"

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


def _style(text: str, *codes: str) -> str:
    return f"{''.join(codes)}{text}{_ANSI_RESET}"


def _label(text: str) -> str:
    return _style(text, _ANSI_BOLD, _ANSI_WHITE)


def _case_color(case_name: str) -> str:
    if case_name == "EQUIVALENT":
        return _ANSI_GREEN
    if case_name in {"PRE_CODE", "POST_CODE"}:
        return _ANSI_YELLOW
    if case_name in {"PRE_SPEC", "POST_SPEC"}:
        return _ANSI_BLUE
    return _ANSI_RED


def _case_badge(case_name: str) -> str:
    if case_name == "EQUIVALENT":
        return _style(f" {case_name} ", _ANSI_BOLD, _ANSI_WHITE, _ANSI_BG_GREEN)
    if case_name in {"PRE_CODE", "POST_CODE"}:
        return _style(f" {case_name} ", _ANSI_BOLD, _ANSI_WHITE, _ANSI_BG_YELLOW)
    if case_name in {"PRE_SPEC", "POST_SPEC"}:
        return _style(f" {case_name} ", _ANSI_BOLD, _ANSI_WHITE, _ANSI_BG_BLUE)
    return _style(f" {case_name} ", _ANSI_BOLD, _ANSI_WHITE, _ANSI_BG_RED)


def _bool_badge(value: bool) -> str:
    if value:
        return _style(" TRUE ", _ANSI_BOLD, _ANSI_WHITE, _ANSI_BG_GREEN)
    return _style(" FALSE ", _ANSI_BOLD, _ANSI_WHITE, _ANSI_BG_RED)


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
    use_llm = os.getenv("DUALIFY_ACTION_PLANNER_LLM", "0") == "1"
    if use_llm:
        try:
            payload = client.generate_json(prompt, temperature=0.0)
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
    else:
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
    if not summary:
        if triggered_case == "EQUIVALENT":
            summary = "No mismatch on common preconditions and postconditions."
        elif triggered_case == "PRE_CODE":
            summary = "Implementation preconditions are stricter than specification."
        elif triggered_case == "PRE_SPEC":
            summary = "Specification preconditions are stricter than implementation."
        elif triggered_case == "POST_CODE":
            summary = "Implementation postconditions are weaker on common preconditions."
        elif triggered_case == "POST_SPEC":
            summary = "Specification postconditions are weaker on common preconditions."
        else:
            summary = "Mismatch detected; review diagnostics and add targeted test."

    return {
        "benchmark_id": benchmark_id,
        "triggered_case": triggered_case,
        "baseline_actions": baseline_actions,
        "recommended_actions": clean_recommended,
        "summary": summary,
    }


def print_comparison_report(
    *,
    benchmark_id: str,
    signature: str,
    informal_spec: str,
    smt_result: SmtResult,
    action_plan: dict,
) -> None:
    triggered_case = action_plan.get("triggered_case", "UNKNOWN")
    if not isinstance(triggered_case, str):
        triggered_case = "UNKNOWN"
    case_color = _case_color(triggered_case)
    header = _style(" Dualify Comparison ", _ANSI_BOLD, _ANSI_WHITE, _ANSI_BG_BLUE)
    divider = _style("━" * 88, _ANSI_CYAN)

    print("\n" + divider)
    print(header)
    print(divider)
    print(_label("Function:"), _style(benchmark_id, _ANSI_BOLD, _ANSI_WHITE))
    print(_label("Signature:"), _style(signature, _ANSI_WHITE))
    print(_label("Spec:"), _style(informal_spec, _ANSI_WHITE))
    print(_label("SMT reason:"), _style(smt_result.reason, _ANSI_CYAN))
    print(_label("Equivalent:"), _bool_badge(smt_result.equivalent))
    print(_label("Triggered case:"), _case_badge(triggered_case))
    print(_label("Counterexample:"), _style(str(smt_result.counterexample), case_color))
    print(_label("Diagnostics:"), _style(str(smt_result.diagnostics or {}), _ANSI_WHITE))
    recommended = action_plan.get("recommended_actions", [])
    if isinstance(recommended, list) and recommended:
        print(_label("Recommended actions:"))
        for item in recommended:
            print(f"  {_style('•', _ANSI_CYAN)} {_style(str(item), _ANSI_WHITE)}")
    else:
        print(_label("Recommended actions:"), _style("[]", _ANSI_WHITE))
    summary = action_plan.get("summary", "")
    if isinstance(summary, str) and summary:
        print(_label("Planner summary:"), _style(summary, _ANSI_WHITE))


def choose_action_interactively(action_plan: dict) -> str:
    recommended = action_plan.get("recommended_actions", [])
    if not isinstance(recommended, list):
        recommended = []
    actions = [item for item in recommended if isinstance(item, str)]

    if not actions:
        print(_style("No actions suggested.", _ANSI_BOLD, _ANSI_YELLOW))
        commands_hint = (
            f"{_style('[n]', _ANSI_CYAN, _ANSI_BOLD)} next  "
            f"{_style('[q]', _ANSI_RED, _ANSI_BOLD)} quit"
        )
        print(_label("Commands:"), commands_hint)
        while True:
            choice = input("Select command: ").strip().lower()
            if choice in {"n", "q"}:
                return "__next__" if choice == "n" else "__quit__"
            print(_style("Invalid command. Use 'n' or 'q'.", _ANSI_RED))

    print("\n" + _style(" Action menu ", _ANSI_BOLD, _ANSI_WHITE, _ANSI_BG_BLUE))
    for idx, action in enumerate(actions, start=1):
        print(
            f"  {_style(f'[{idx}]', _ANSI_CYAN, _ANSI_BOLD)} "
            f"{_style(action, _ANSI_WHITE)}"
        )
    print(
        f"  {_style('[n]', _ANSI_CYAN, _ANSI_BOLD)} "
        f"{_style('next function', _ANSI_WHITE)}"
    )
    print(
        f"  {_style('[q]', _ANSI_RED, _ANSI_BOLD)} "
        f"{_style('quit', _ANSI_WHITE)}"
    )

    while True:
        choice = input("Select action: ").strip().lower()
        if choice == "n":
            return "__next__"
        if choice == "q":
            return "__quit__"
        if choice.isdigit():
            index = int(choice) - 1
            if 0 <= index < len(actions):
                return actions[index]
        print(_style("Invalid choice. Enter action number, 'n', or 'q'.", _ANSI_RED))

