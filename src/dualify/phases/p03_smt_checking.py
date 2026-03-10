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


def _make_var(name: str, type_name: str) -> Any:
    if type_name == "int":
        return z3.Int(name)
    if type_name == "bool":
        return z3.Bool(name)
    raise ValueError(f"Unsupported type: {type_name}")


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
    env = {
        "And": z3.And,
        "Or": z3.Or,
        "Not": z3.Not,
        "Implies": z3.Implies,
        "If": z3.If,
        "Abs": z3.Abs,
        "True": True,
        "False": False,
    }
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


def check_equivalence(
    case_spec: CaseSpec,
    spec_logic: ExtractionResult,
    code_logic: ExtractionResult,
) -> SmtResult:
    scope: dict[str, Any] = {}
    for arg_name, type_name in case_spec.arg_types.items():
        scope[arg_name] = _make_var(arg_name, type_name)
    scope["ret"] = _make_var("ret", case_spec.return_type)

    try:
        clean_spec_constraints = _strip_exhaustive_zero_split_constraints(
            spec_logic.domain_constraints
        )
        clean_code_constraints = _strip_exhaustive_zero_split_constraints(
            code_logic.domain_constraints
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

    def model_to_counterexample(model: z3.ModelRef) -> dict[str, int | bool]:
        counterexample: dict[str, int | bool] = {}
        for arg_name in case_spec.arg_types:
            value = model.eval(scope[arg_name], model_completion=True)
            if z3.is_bool(value):
                counterexample[arg_name] = z3.is_true(value)
            else:
                counterexample[arg_name] = value.as_long()
        ret_value = model.eval(scope["ret"], model_completion=True)
        if z3.is_bool(ret_value):
            counterexample["ret"] = z3.is_true(ret_value)
        else:
            counterexample["ret"] = ret_value.as_long()
        return counterexample

    # Step 1 from scheme: precondition mismatch check.
    pre_xor_solver = z3.Solver()
    pre_xor_solver.add(z3.Xor(spec_assumptions, code_assumptions))
    pre_xor_result = pre_xor_solver.check()
    preconditions_mismatch = pre_xor_result == z3.sat
    preconditions_counterexample = (
        model_to_counterexample(pre_xor_solver.model()) if preconditions_mismatch else None
    )

    spec_implies_code_solver = z3.Solver()
    spec_implies_code_solver.add(spec_assumptions)
    spec_implies_code_solver.add(z3.Not(code_assumptions))
    spec_implies_code = spec_implies_code_solver.check() == z3.unsat

    code_implies_spec_solver = z3.Solver()
    code_implies_spec_solver.add(code_assumptions)
    code_implies_spec_solver.add(z3.Not(spec_assumptions))
    code_implies_spec = code_implies_spec_solver.check() == z3.unsat

    diagnostics: dict[str, object] = {
        "pre_mismatch": preconditions_mismatch,
        "pre_spec_implies_pre_code": spec_implies_code,
        "pre_code_implies_pre_spec": code_implies_spec,
        "pre_counterexample": preconditions_counterexample,
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
    post_mismatch_solver.add(common_domain, z3.Xor(spec_post, code_post))
    post_mismatch_result = post_mismatch_solver.check()
    post_mismatch = post_mismatch_result == z3.sat
    post_mismatch_counterexample = (
        model_to_counterexample(post_mismatch_solver.model()) if post_mismatch else None
    )

    diagnostics["post_mismatch_on_common_pre"] = post_mismatch
    diagnostics["post_mismatch_counterexample"] = post_mismatch_counterexample

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
    spec_post_implies_code_solver.add(common_domain, spec_post, z3.Not(code_post))
    spec_post_implies_code = spec_post_implies_code_solver.check() == z3.unsat

    code_post_implies_spec_solver = z3.Solver()
    code_post_implies_spec_solver.add(common_domain, code_post, z3.Not(spec_post))
    code_post_implies_spec = code_post_implies_spec_solver.check() == z3.unsat

    diagnostics["post_spec_implies_post_code_on_common_pre"] = spec_post_implies_code
    diagnostics["post_code_implies_post_spec_on_common_pre"] = code_post_implies_spec

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
    for arg_name, type_name in case_spec.arg_types.items():
        scope[arg_name] = _make_var(arg_name, type_name)
    scope["ret"] = _make_var("ret", case_spec.return_type)
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
    try:
        for c in normalized_constraints:
            _safe_eval(c, scope, case_spec.benchmark_id)
        _safe_eval(normalized_post, scope, case_spec.benchmark_id)
    except Exception:
        return False
    return True

