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
    "investigate_instrumentation",
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
    if case_name == "LOW_CONFIDENCE_PARSE":
        return _ANSI_YELLOW
    return _ANSI_RED


def _case_badge(case_name: str) -> str:
    if case_name == "EQUIVALENT":
        return _style(f" {case_name} ", _ANSI_BOLD, _ANSI_WHITE, _ANSI_BG_GREEN)
    if case_name in {"PRE_CODE", "POST_CODE"}:
        return _style(f" {case_name} ", _ANSI_BOLD, _ANSI_WHITE, _ANSI_BG_YELLOW)
    if case_name in {"PRE_SPEC", "POST_SPEC"}:
        return _style(f" {case_name} ", _ANSI_BOLD, _ANSI_WHITE, _ANSI_BG_BLUE)
    if case_name == "LOW_CONFIDENCE_PARSE":
        return _style(f" {case_name} ", _ANSI_BOLD, _ANSI_WHITE, _ANSI_BG_YELLOW)
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
                "fix_implementation",
                "add_test_case",
                "add_property_to_ignore_list",
            ],
        )
    if reason == "case_post_spec":
        return (
            "POST_SPEC",
            [
                "fix_implementation",
                "refine_spec",
                "add_test_case",
                "add_property_to_ignore_list",
            ],
        )
    if reason == "low_confidence_parse":
        return (
            "LOW_CONFIDENCE_PARSE",
            [
                "refine_spec",
                "fix_implementation",
                "investigate_instrumentation",
                "no_test_case",
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
                    "fix_implementation",
                    "add_test_case",
                    "add_property_to_ignore_list",
                ],
            )
        return (
            "POST_SPEC",
            [
                "fix_implementation",
                "refine_spec",
                "add_test_case",
                "add_property_to_ignore_list",
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
     actions = [refine_spec, fix_implementation, add_test_case, add_property_to_ignore_list]
   - else:
     triggered_case = POST_SPEC
     actions = [fix_implementation, refine_spec, add_test_case, add_property_to_ignore_list]
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
        elif triggered_case == "LOW_CONFIDENCE_PARSE":
            summary = (
                "SMT matched, but extracted formulas are low-confidence; "
                "refine spec/implementation or investigate extraction instrumentation."
            )
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
    file_path: str,
    lineno: int,
    signature: str,
    informal_spec: str,
    smt_result: SmtResult,
    action_plan: dict,
    verbose: bool = False,
    spec_logic: dict | None = None,
    code_logic: dict | None = None,
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
    print(_label("Location:"), _style(f"{file_path}:{lineno}", _ANSI_BOLD, _ANSI_WHITE))
    print(_label("Target:"), _style(benchmark_id, _ANSI_BOLD, _ANSI_WHITE))
    print(_label("Signature:"), _style(signature, _ANSI_WHITE))
    print(_label("SMT reason:"), _style(smt_result.reason, _ANSI_CYAN))
    print(_label("Equivalent:"), _bool_badge(smt_result.equivalent))
    print(_label("Triggered case:"), _case_badge(triggered_case))
    print(_label("Counterexample(args):"), _style(str(smt_result.counterexample), case_color))
    diagnostics = smt_result.diagnostics or {}
    short_diagnostics = {
        "pre_mismatch": diagnostics.get("pre_mismatch"),
        "post_mismatch_on_common_pre": diagnostics.get("post_mismatch_on_common_pre"),
        "failed_check": diagnostics.get("failed_check"),
        "parse_low_confidence": diagnostics.get("parse_low_confidence"),
        "spec_weak_postcondition": diagnostics.get("spec_weak_postcondition"),
        "code_weak_postcondition": diagnostics.get("code_weak_postcondition"),
    }
    print(_label("Diagnostics(short):"), _style(str(short_diagnostics), _ANSI_WHITE))

    def _print_trace(title: str, logic: dict) -> None:
        trace = logic.get("extraction_trace")
        if not isinstance(trace, dict) or not trace:
            return
        print(_label(title))
        for stage in ("initial", "repair", "safe_repair", "final"):
            stage_payload = trace.get(stage)
            if not isinstance(stage_payload, dict):
                continue
            constraints = stage_payload.get("domain_constraints", [])
            postcondition = stage_payload.get("postcondition", "")
            errors = stage_payload.get("errors", [])
            degraded = stage_payload.get("degraded")
            degraded_reason = stage_payload.get("degraded_reason")

            print("  " + _style(f"[{stage}]", _ANSI_BOLD, _ANSI_CYAN))
            print(
                "    "
                + _style("PRE:", _ANSI_BOLD, _ANSI_BLUE)
                + " "
                + _style(str(constraints), _ANSI_WHITE)
            )
            print(
                "    "
                + _style("POST:", _ANSI_BOLD, _ANSI_YELLOW)
                + " "
                + _style(str(postcondition), _ANSI_BOLD, _ANSI_WHITE)
            )
            if isinstance(errors, list) and errors:
                print(
                    "    "
                    + _style("ERRORS:", _ANSI_BOLD, _ANSI_RED)
                    + " "
                    + _style(str(errors), _ANSI_WHITE)
                )
            if isinstance(degraded, bool):
                print(
                    "    "
                    + _style("DEGRADED:", _ANSI_BOLD, _ANSI_RED if degraded else _ANSI_GREEN)
                    + " "
                    + _style(str(degraded), _ANSI_WHITE)
                )
            if isinstance(degraded_reason, str) and degraded_reason:
                print(
                    "    "
                    + _style("DEGRADED_REASON:", _ANSI_BOLD, _ANSI_RED)
                    + " "
                    + _style(degraded_reason, _ANSI_WHITE)
                )

    if isinstance(spec_logic, dict):
        print(
            _label("Spec preconditions:"),
            _style(str(spec_logic.get("domain_constraints", [])), _ANSI_WHITE),
        )
        print(
            _label("Spec postcondition:"),
            _style(str(spec_logic.get("postcondition", "")), _ANSI_WHITE),
        )
        _print_trace("Spec extraction trace:", spec_logic)
    if isinstance(code_logic, dict):
        print(
            _label("Implementation preconditions:"),
            _style(str(code_logic.get("domain_constraints", [])), _ANSI_WHITE),
        )
        print(
            _label("Implementation postcondition:"),
            _style(str(code_logic.get("postcondition", "")), _ANSI_WHITE),
        )
        _print_trace("Implementation extraction trace:", code_logic)
    if verbose:
        print(_label("Spec:"), _style(informal_spec, _ANSI_WHITE))
        debug = diagnostics.get("debug", {})
        if isinstance(debug, dict):
            formulas = debug.get("formulas", {})
            checks = debug.get("checks", {})
            witness_model = debug.get("witness_model", {})
            print(_label("Formulas:"), _style(str(formulas), _ANSI_WHITE))
            failed_check = diagnostics.get("failed_check")
            if isinstance(failed_check, str) and isinstance(checks, dict):
                print(
                    _label("Broken check:"),
                    _style(f"{failed_check}: {checks.get(failed_check)}", _ANSI_WHITE),
                )
            print(_label("Witness:"), _style(str(witness_model), _ANSI_WHITE))
        print(_label("Diagnostics(full):"), _style(str(diagnostics), _ANSI_WHITE))
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


def _expand_numeric_selection(raw: str, upper: int) -> list[int]:
    normalized = raw.replace(",", " ")
    tokens = [token for token in normalized.split() if token]
    result: list[int] = []
    for token in tokens:
        if "-" in token:
            bounds = token.split("-", maxsplit=1)
            if len(bounds) != 2 or not bounds[0].isdigit() or not bounds[1].isdigit():
                return []
            start = int(bounds[0])
            end = int(bounds[1])
            if start < 1 or end < 1 or start > end or end > upper:
                return []
            for value in range(start, end + 1):
                if value not in result:
                    result.append(value)
            continue
        if not token.isdigit():
            return []
        index = int(token)
        if index < 1 or index > upper:
            return []
        if index not in result:
            result.append(index)
    return result


def choose_action_interactively(action_plan: dict) -> str | list[str]:
    recommended = action_plan.get("recommended_actions", [])
    if not isinstance(recommended, list):
        recommended = []
    actions = [item for item in recommended if isinstance(item, str)]

    if not actions:
        print(_style("No actions suggested.", _ANSI_BOLD, _ANSI_YELLOW))
        commands_hint = (
            f"{_style('[d]', _ANSI_CYAN, _ANSI_BOLD)} details  "
            f"{_style('[n]', _ANSI_CYAN, _ANSI_BOLD)} next  "
            f"{_style('[q]', _ANSI_RED, _ANSI_BOLD)} quit"
        )
        print(_label("Commands:"), commands_hint)
        while True:
            choice = input("Select command: ").strip().lower()
            if choice in {"n", "q"}:
                return "__next__" if choice == "n" else "__quit__"
            if choice == "d":
                return "__details__"
            print(_style("Invalid command. Use 'd', 'n', or 'q'.", _ANSI_RED))

    print("\n" + _style(" Action menu ", _ANSI_BOLD, _ANSI_WHITE, _ANSI_BG_BLUE))
    for idx, action in enumerate(actions, start=1):
        print(
            f"  {_style(f'[{idx}]', _ANSI_CYAN, _ANSI_BOLD)} "
            f"{_style(action, _ANSI_WHITE)}"
        )
    print(
        f"  {_style('[a]', _ANSI_CYAN, _ANSI_BOLD)} "
        f"{_style('all recommended', _ANSI_WHITE)}"
    )
    print(
        f"  {_style('[d]', _ANSI_CYAN, _ANSI_BOLD)} "
        f"{_style('show details', _ANSI_WHITE)}"
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
        if choice == "d":
            return "__details__"
        if choice == "a":
            return actions
        indexes = _expand_numeric_selection(choice, len(actions))
        if indexes:
            selected = [actions[idx - 1] for idx in indexes]
            if len(selected) == 1:
                return selected[0]
            return selected
        print(_style("Invalid choice. Enter action index/range, 'a', 'd', 'n', or 'q'.", _ANSI_RED))

