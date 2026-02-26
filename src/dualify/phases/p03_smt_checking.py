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
    if re.fullmatch(r"\s*[A-Za-z_][A-Za-z0-9_]*\s+is\s+an?\s+integer\s*", rewritten):
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
    rewritten = rewritten.replace("<->", " == ")
    rewritten = rewritten.replace("&&", " and ")
    rewritten = rewritten.replace("||", " or ")
    rewritten = rewritten.replace("->", " >> ")
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
        spec_constraints = [
            _safe_eval(c, scope, case_spec.benchmark_id) for c in spec_logic.domain_constraints
        ]
        code_constraints = [
            _safe_eval(c, scope, case_spec.benchmark_id) for c in code_logic.domain_constraints
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

    solver = z3.Solver()
    for c in spec_constraints:
        solver.add(c)
    for c in code_constraints:
        solver.add(c)
    solver.add(z3.Xor(spec_post, code_post))

    result = solver.check()
    if result == z3.unsat:
        return SmtResult(
            benchmark_id=case_spec.benchmark_id,
            equivalent=True,
            reason="formulas_equivalent_under_constraints",
            counterexample=None,
        )

    if result != z3.sat:
        return SmtResult(
            benchmark_id=case_spec.benchmark_id,
            equivalent=False,
            reason=f"solver_result_{result}",
            counterexample=None,
        )

    model = solver.model()
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

    return SmtResult(
        benchmark_id=case_spec.benchmark_id,
        equivalent=False,
        reason="counterexample_found",
        counterexample=counterexample,
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

