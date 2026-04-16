import ast
import re
from dataclasses import dataclass
from typing import Any

import z3

from dualify.types import ExtractionResult, SmtResult


@dataclass
class CaseSpec:
    benchmark_id: str
    arg_types: dict[str, str]
    return_type: str


def _sanitize_sort_name(type_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", type_name).strip("_")
    return cleaned or "Unknown"


def _sort_for_type(type_name: str) -> z3.SortRef:
    if type_name == "int":
        return z3.IntSort()
    if type_name == "bool":
        return z3.BoolSort()
    if type_name == "float":
        return z3.RealSort()
    if type_name == "str":
        return z3.StringSort()
    list_match = re.fullmatch(r"list\[(.+)\]", type_name)
    if list_match:
        item_type = list_match.group(1).strip()
        return z3.SeqSort(_sort_for_type(item_type))
    return z3.DeclareSort(f"T_{_sanitize_sort_name(type_name)}")


def _make_var(name: str, type_name: str) -> Any:
    return z3.Const(name, _sort_for_type(type_name))


class _BoolOpTransformer(ast.NodeTransformer):
    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        self.generic_visit(node)
        func_name = "And" if isinstance(node.op, ast.And) else "Or"
        return ast.Call(func=ast.Name(id=func_name, ctx=ast.Load()), args=node.values, keywords=[])

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.op, ast.Not):
            return ast.Call(
                func=ast.Name(id="Not", ctx=ast.Load()),
                args=[node.operand],
                keywords=[],
            )
        return node

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.op, ast.RShift):
            return ast.Call(
                func=ast.Name(id="Implies", ctx=ast.Load()),
                args=[node.left, node.right],
                keywords=[],
            )
        return node


def _rewrite_expression(expr: str, benchmark_id: str) -> str:
    rewritten = expr
    if re.fullmatch(
        r"\s*[A-Za-z_][A-Za-z0-9_]*\s+is\s+an?\s+(?:integer|int)\s*",
        rewritten,
    ):
        return "True"

    rewritten = re.sub(
        rf"\b{re.escape(benchmark_id)}\s*\([^)]*\)",
        "ret",
        rewritten,
    )
    rewritten = re.sub(r"\bEven\s*\(\s*([^()]+)\s*\)", r"((\1) % 2 == 0)", rewritten)
    rewritten = rewritten.replace("/\\", " and ")
    rewritten = rewritten.replace("\\/", " or ")
    rewritten = rewritten.replace("==>", " >> ")
    rewritten = rewritten.replace("=>", " >> ")
    rewritten = rewritten.replace("<->", " == ")
    rewritten = rewritten.replace("&&", " and ")
    rewritten = rewritten.replace("||", " or ")
    rewritten = rewritten.replace("->", " >> ")
    rewritten = rewritten.replace(";", " and ")
    rewritten = rewritten.replace("//", "/")
    rewritten = re.sub(r"\blen\s*\(", "Length(", rewritten)
    rewritten = re.sub(
        r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b",
        r"\1_\2",
        rewritten,
    )
    rewritten = re.sub(r"\bAnd\b(?!\()", " and ", rewritten)
    rewritten = re.sub(r"\bOr\b(?!\()", " or ", rewritten)
    rewritten = re.sub(r"\bNot\b(?!\()", " not ", rewritten)
    rewritten = re.sub(r"\bImplies\b(?!\()", " >> ", rewritten)
    return rewritten


def _canonicalize_expression(expr: str, benchmark_id: str) -> str:
    rewritten = _rewrite_expression(expr, benchmark_id)
    try:
        parsed = ast.parse(rewritten, mode="eval")
        transformed = _BoolOpTransformer().visit(parsed)
        ast.fix_missing_locations(transformed)
        return ast.unparse(transformed)
    except Exception:
        return rewritten


def _safe_eval(expr: str, scope: dict[str, Any], benchmark_id: str) -> Any:
    normalized_expr = _canonicalize_expression(expr, benchmark_id)
    sqrt_fn = z3.Function("sqrt", z3.RealSort(), z3.RealSort())

    def _floor(value: Any) -> Any:
        return z3.ToInt(value)

    def _sqrt(value: Any) -> Any:
        if hasattr(z3, "Sqrt"):
            return z3.Sqrt(value)
        return sqrt_fn(value)

    def _pow(lhs: Any, rhs: Any) -> Any:
        return lhs**rhs

    def _is_digit_string(value: Any) -> Any:
        if hasattr(z3, "InRe"):
            return z3.InRe(value, z3.Star(z3.Range("0", "9")))
        return z3.BoolVal(True)

    z3_callables = {
        name: getattr(z3, name)
        for name in dir(z3)
        if not name.startswith("_") and callable(getattr(z3, name, None))
    }
    env = {
        "And": z3.And,
        "Or": z3.Or,
        "Not": z3.Not,
        "Implies": z3.Implies,
        "If": z3.If,
        "Abs": z3.Abs,
        "Length": z3.Length,
        "Contains": z3.Contains,
        "PrefixOf": z3.PrefixOf,
        "SuffixOf": z3.SuffixOf,
        "Concat": z3.Concat,
        "floor": _floor,
        "sqrt": _sqrt,
        "pow": _pow,
        "IsDigitString": _is_digit_string,
        "True": True,
        "False": False,
    }
    env.update(z3_callables)
    env.update(scope)
    return eval(normalized_expr, {"__builtins__": {}}, env)


def _has_forbidden_python_bool_ops(expr: str) -> bool:
    return bool(re.search(r"(^|\s)(and|or|not)(\s|$)", expr))


def _has_bool_arithmetic_hint(expr: str) -> bool:
    # Conservative guard: blocks frequent invalid patterns like a*(x > 0).
    has_arith_before_group = any(
        token in expr for token in ("*(", "* (", "+(", "+ (", "-(", "- (", "/(", "/ (")
    )
    has_comparator = any(token in expr for token in ("==", "!=", "<=", ">=", "<", ">"))
    return has_arith_before_group and has_comparator


def _mod_denominators(expr: str) -> list[str]:
    # Capture simple denominator symbols in `lhs % den`.
    return re.findall(r"%\s*([A-Za-z_][A-Za-z0-9_]*)", expr)


def _has_guard_for_denominator(den: str, all_expr_text: str) -> bool:
    guard_patterns = [
        f"{den} != 0",
        f"Not({den} == 0)",
        f"Not({den}==0)",
        f"If({den} == 0",
        f"If({den}==0",
    ]
    return any(pattern in all_expr_text for pattern in guard_patterns)


def _validate_formula_safety(extraction: ExtractionResult) -> list[str]:
    issues: list[str] = []
    expressions = [*extraction.domain_constraints, extraction.postcondition]
    all_expr_text = " ".join(expressions)

    for expr in expressions:
        if _has_forbidden_python_bool_ops(expr):
            issues.append("forbidden_python_bool_ops")
            break
        if _has_bool_arithmetic_hint(expr):
            issues.append("bool_arithmetic_mix")
            break

    denominators: set[str] = set()
    for expr in expressions:
        denominators.update(_mod_denominators(expr))
    for den in sorted(denominators):
        if not _has_guard_for_denominator(den, all_expr_text):
            issues.append(f"unguarded_mod_denominator:{den}")

    return issues


def _strip_exhaustive_zero_split_constraints(constraints: list[str]) -> list[str]:
    pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(>=|>|<=|<)\s*0\s*$")
    index_by_key: dict[tuple[str, str], set[int]] = {}
    for i, expr in enumerate(constraints):
        match = pattern.fullmatch(expr)
        if not match:
            continue
        var_name, op = match.group(1), match.group(2)
        index_by_key.setdefault((var_name, op), set()).add(i)

    complementary_pairs = [(">=", "<"), (">", "<="), ("<=", ">"), ("<", ">=")]
    drop_indexes: set[int] = set()
    variables = {var for (var, _op) in index_by_key}
    for var in variables:
        for lhs, rhs in complementary_pairs:
            lhs_indexes = index_by_key.get((var, lhs), set())
            rhs_indexes = index_by_key.get((var, rhs), set())
            if lhs_indexes and rhs_indexes:
                drop_indexes.update(lhs_indexes)
                drop_indexes.update(rhs_indexes)

    return [expr for idx, expr in enumerate(constraints) if idx not in drop_indexes]


_TOKEN_PATTERN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_RESERVED_FORMULA_TOKENS = {
    "True",
    "False",
}


def _infer_symbol_type(name: str, expressions: list[str]) -> str:
    joined = " ".join(expressions)
    if re.search(rf"\bLength\s*\(\s*{re.escape(name)}\b", joined):
        return "str"
    if re.search(rf"\b{re.escape(name)}\s*[%+\-*/<>]", joined) or re.search(
        rf"[%+\-*/<>]\s*{re.escape(name)}\b",
        joined,
    ):
        return "int"
    return "str"


def _augment_scope_from_formulas(
    scope: dict[str, Any],
    known_names: set[str],
    expressions: list[str],
) -> None:
    found_names: set[str] = set()
    for expr in expressions:
        called_names: set[str] = set()
        try:
            tree = ast.parse(expr, mode="eval")
            called_names = {
                node.func.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
        except Exception:
            called_names = set()
        for token in _TOKEN_PATTERN.findall(expr):
            if token in _RESERVED_FORMULA_TOKENS:
                continue
            if token in called_names:
                continue
            if token.isdigit():
                continue
            found_names.add(token)
    for name in sorted(found_names):
        if name in known_names:
            continue
        inferred_type = _infer_symbol_type(name, expressions)
        scope[name] = _make_var(name, inferred_type)
        known_names.add(name)


def check_equivalence(
    case_spec: CaseSpec,
    spec_logic: ExtractionResult,
    code_logic: ExtractionResult,
) -> SmtResult:
    scope: dict[str, Any] = {}
    known_names: set[str] = set()
    for arg_name, type_name in case_spec.arg_types.items():
        scope[arg_name] = _make_var(arg_name, type_name)
        known_names.add(arg_name)
    scope["ret"] = _make_var("ret", case_spec.return_type)
    known_names.add("ret")

    try:
        clean_spec_constraints = _strip_exhaustive_zero_split_constraints(
            spec_logic.domain_constraints
        )
        clean_code_constraints = _strip_exhaustive_zero_split_constraints(
            code_logic.domain_constraints
        )
        _augment_scope_from_formulas(
            scope,
            known_names,
            [
                *clean_spec_constraints,
                *clean_code_constraints,
                spec_logic.postcondition,
                code_logic.postcondition,
            ],
        )
        spec_constraints = [
            _safe_eval(c, scope, case_spec.benchmark_id) for c in clean_spec_constraints
        ]
        code_constraints = [
            _safe_eval(c, scope, case_spec.benchmark_id) for c in clean_code_constraints
        ]
        spec_post = _safe_eval(spec_logic.postcondition, scope, case_spec.benchmark_id)
        code_post = _safe_eval(code_logic.postcondition, scope, case_spec.benchmark_id)
    except Exception as exc:
        return SmtResult(
            benchmark_id=case_spec.benchmark_id,
            equivalent=False,
            reason=f"formula_parse_error: {exc}",
            counterexample=None,
        )

    spec_assumptions = z3.And(*spec_constraints) if spec_constraints else z3.BoolVal(True)
    code_assumptions = z3.And(*code_constraints) if code_constraints else z3.BoolVal(True)

    def _numeric_from_model_value(value: z3.ExprRef) -> int | float:
        if z3.is_int_value(value):
            return value.as_long()
        if z3.is_rational_value(value):
            return float(value.as_fraction())
        # Fallback for numerals that are not plain int/rational.
        return float(value.as_decimal(20).replace("?", ""))

    def _model_value_to_python(value: z3.ExprRef) -> int | float | bool | str:
        if z3.is_bool(value):
            return z3.is_true(value)
        if z3.is_int_value(value) or z3.is_rational_value(value):
            return _numeric_from_model_value(value)
        if z3.is_string_value(value):
            return value.as_string()
        return str(value)

    def model_to_counterexample(
        model: z3.ModelRef,
        *,
        include_ret: bool,
    ) -> dict[str, int | float | bool | str]:
        counterexample: dict[str, int | float | bool | str] = {}
        for arg_name in case_spec.arg_types:
            value = model.eval(scope[arg_name], model_completion=True)
            counterexample[arg_name] = _model_value_to_python(value)
        if include_ret:
            ret_value = model.eval(scope["ret"], model_completion=True)
            counterexample["ret"] = _model_value_to_python(ret_value)
        return counterexample

    def _z3_expr_to_text(expr: Any) -> str:
        if hasattr(expr, "sexpr"):
            return str(expr.sexpr())
        return str(expr)

    # Step 1 from scheme: precondition mismatch check.
    pre_xor_solver = z3.Solver()
    pre_mismatch_check = z3.Xor(spec_assumptions, code_assumptions)
    pre_xor_solver.add(pre_mismatch_check)
    pre_xor_result = pre_xor_solver.check()
    preconditions_mismatch = pre_xor_result == z3.sat
    preconditions_counterexample = None
    pre_mismatch_witness = None
    if preconditions_mismatch:
        pre_model = pre_xor_solver.model()
        preconditions_counterexample = model_to_counterexample(pre_model, include_ret=False)
        pre_mismatch_witness = model_to_counterexample(pre_model, include_ret=True)

    spec_implies_code_solver = z3.Solver()
    pre_spec_to_pre_code_implication = z3.Implies(spec_assumptions, code_assumptions)
    spec_implies_code_solver.add(z3.Not(pre_spec_to_pre_code_implication))
    spec_implies_code_status = spec_implies_code_solver.check()
    spec_implies_code = spec_implies_code_status == z3.unsat
    pre_spec_implies_pre_code_witness = (
        model_to_counterexample(spec_implies_code_solver.model(), include_ret=True)
        if spec_implies_code_status == z3.sat
        else None
    )

    code_implies_spec_solver = z3.Solver()
    pre_code_to_pre_spec_implication = z3.Implies(code_assumptions, spec_assumptions)
    code_implies_spec_solver.add(z3.Not(pre_code_to_pre_spec_implication))
    code_implies_spec_status = code_implies_spec_solver.check()
    code_implies_spec = code_implies_spec_status == z3.unsat
    pre_code_implies_pre_spec_witness = (
        model_to_counterexample(code_implies_spec_solver.model(), include_ret=True)
        if code_implies_spec_status == z3.sat
        else None
    )

    failed_check = "none"
    if preconditions_mismatch:
        failed_check = "pre_mismatch_check"
    diagnostics: dict[str, object] = {
        "pre_mismatch": preconditions_mismatch,
        "pre_spec_implies_pre_code": spec_implies_code,
        "pre_code_implies_pre_spec": code_implies_spec,
        "pre_counterexample": preconditions_counterexample,
        "failed_check": failed_check,
        "debug": {
            "formulas": {
                "pre_spec": _z3_expr_to_text(spec_assumptions),
                "pre_code": _z3_expr_to_text(code_assumptions),
                "common_pre": _z3_expr_to_text(z3.And(spec_assumptions, code_assumptions)),
                "post_spec": _z3_expr_to_text(spec_post),
                "post_code": _z3_expr_to_text(code_post),
            },
            "checks": {
                "pre_mismatch_check": _z3_expr_to_text(pre_mismatch_check),
                "post_mismatch_check": _z3_expr_to_text(
                    z3.Implies(
                        z3.And(spec_assumptions, code_assumptions),
                        z3.Xor(spec_post, code_post),
                    )
                ),
                "spec_post_implies_code_post": _z3_expr_to_text(
                    z3.Implies(
                        z3.And(z3.And(spec_assumptions, code_assumptions), spec_post),
                        code_post,
                    )
                ),
                "code_post_implies_spec_post": _z3_expr_to_text(
                    z3.Implies(
                        z3.And(z3.And(spec_assumptions, code_assumptions), code_post),
                        spec_post,
                    )
                ),
            },
            "witness_model": {
                "pre_mismatch_check": pre_mismatch_witness,
                "pre_spec_implies_pre_code": pre_spec_implies_pre_code_witness,
                "pre_code_implies_pre_spec": pre_code_implies_pre_spec_witness,
                "post_mismatch_check": None,
                "spec_post_implies_code_post": None,
                "code_post_implies_spec_post": None,
            },
        },
    }

    common_domain = z3.And(spec_assumptions, code_assumptions)

    # Step 1a from scheme:
    # if pre mismatch, classify PRE_CODE vs PRE_SPEC and finish early.
    if preconditions_mismatch:
        if not spec_implies_code:
            return SmtResult(
                benchmark_id=case_spec.benchmark_id,
                equivalent=False,
                reason="case_pre_code",
                counterexample=preconditions_counterexample,
                diagnostics=diagnostics,
            )
        return SmtResult(
            benchmark_id=case_spec.benchmark_id,
            equivalent=False,
            reason="case_pre_spec",
            counterexample=preconditions_counterexample,
            diagnostics=diagnostics,
        )

    # Step 2 from scheme (evaluated only after pre checks are common):
    # post mismatch on common domain?
    post_mismatch_solver = z3.Solver()
    post_disagreement_implication = z3.Implies(common_domain, z3.Xor(spec_post, code_post))
    post_mismatch_solver.add(common_domain)
    post_mismatch_solver.add(post_disagreement_implication)
    post_mismatch_result = post_mismatch_solver.check()
    post_mismatch = post_mismatch_result == z3.sat
    post_mismatch_counterexample = None
    post_mismatch_witness = None
    if post_mismatch:
        post_model = post_mismatch_solver.model()
        post_mismatch_counterexample = model_to_counterexample(post_model, include_ret=False)
        post_mismatch_witness = model_to_counterexample(post_model, include_ret=True)

    diagnostics["post_mismatch_on_common_pre"] = post_mismatch
    diagnostics["post_mismatch_counterexample"] = post_mismatch_counterexample
    debug = diagnostics.get("debug")
    if isinstance(debug, dict):
        witness_model = debug.get("witness_model")
        if isinstance(witness_model, dict):
            witness_model["post_mismatch_check"] = post_mismatch_witness

    if not post_mismatch:
        return SmtResult(
            benchmark_id=case_spec.benchmark_id,
            equivalent=True,
            reason="equivalent_no_mismatch",
            counterexample=None,
            diagnostics=diagnostics,
        )

    # Step 3 from scheme (only after mismatch from step 2):
    # Implies(And(common_pre, post_spec), post_code) ?
    spec_post_implies_code_solver = z3.Solver()
    spec_to_code_implication = z3.Implies(z3.And(common_domain, spec_post), code_post)
    spec_post_implies_code_solver.add(z3.Not(spec_to_code_implication))
    spec_post_implies_code_status = spec_post_implies_code_solver.check()
    spec_post_implies_code = spec_post_implies_code_status == z3.unsat
    spec_post_implies_code_witness = (
        model_to_counterexample(spec_post_implies_code_solver.model(), include_ret=True)
        if spec_post_implies_code_status == z3.sat
        else None
    )

    code_post_implies_spec_solver = z3.Solver()
    code_to_spec_implication = z3.Implies(z3.And(common_domain, code_post), spec_post)
    code_post_implies_spec_solver.add(z3.Not(code_to_spec_implication))
    code_post_implies_spec_status = code_post_implies_spec_solver.check()
    code_post_implies_spec = code_post_implies_spec_status == z3.unsat
    code_post_implies_spec_witness = (
        model_to_counterexample(code_post_implies_spec_solver.model(), include_ret=True)
        if code_post_implies_spec_status == z3.sat
        else None
    )

    diagnostics["post_spec_implies_post_code_on_common_pre"] = spec_post_implies_code
    diagnostics["post_code_implies_post_spec_on_common_pre"] = code_post_implies_spec
    if not spec_post_implies_code:
        diagnostics["failed_check"] = "spec_post_implies_code_post"
    elif not code_post_implies_spec:
        diagnostics["failed_check"] = "code_post_implies_spec_post"
    else:
        diagnostics["failed_check"] = "post_mismatch_check"
    debug = diagnostics.get("debug")
    if isinstance(debug, dict):
        witness_model = debug.get("witness_model")
        if isinstance(witness_model, dict):
            witness_model["spec_post_implies_code_post"] = spec_post_implies_code_witness
            witness_model["code_post_implies_spec_post"] = code_post_implies_spec_witness

    reason = "case_post_code" if not spec_post_implies_code else "case_post_spec"
    return SmtResult(
        benchmark_id=case_spec.benchmark_id,
        equivalent=False,
        reason=reason,
        counterexample=post_mismatch_counterexample,
        diagnostics=diagnostics,
    )


def is_parseable(case_spec: CaseSpec, extraction: ExtractionResult) -> bool:
    scope: dict[str, Any] = {}
    known_names: set[str] = set()
    for arg_name, type_name in case_spec.arg_types.items():
        scope[arg_name] = _make_var(arg_name, type_name)
        known_names.add(arg_name)
    scope["ret"] = _make_var("ret", case_spec.return_type)
    known_names.add("ret")
    normalized_constraints = [
        _canonicalize_expression(c, case_spec.benchmark_id) for c in extraction.domain_constraints
    ]
    normalized_post = _canonicalize_expression(extraction.postcondition, case_spec.benchmark_id)
    normalized_extraction = ExtractionResult(
        benchmark_id=extraction.benchmark_id,
        args=extraction.args,
        return_type=extraction.return_type,
        domain_constraints=normalized_constraints,
        postcondition=normalized_post,
        confidence=extraction.confidence,
        notes=extraction.notes,
    )
    safety_issues = _validate_formula_safety(normalized_extraction)
    if safety_issues:
        return False
    _augment_scope_from_formulas(
        scope,
        known_names,
        [*normalized_constraints, normalized_post],
    )
    try:
        for c in normalized_constraints:
            _safe_eval(c, scope, case_spec.benchmark_id)
        _safe_eval(normalized_post, scope, case_spec.benchmark_id)
    except Exception:
        return False
    return True

