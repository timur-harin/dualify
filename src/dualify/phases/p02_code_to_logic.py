import json
import re
from typing import TypedDict

from dualify.ollama_client import OllamaClient
from dualify.types import ExtractionResult

_FORBIDDEN_EXPR_PATTERN = re.compile(
    r"\bfloor\b|\bsqrt\b|\bpow\b|\blambda\b|\*\*|//|\[|\]|\{|\}"
)
_IDENTIFIER_PATTERN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_INFIX_BOOL_PATTERN = re.compile(r"\s(And|Or)\s")
_LOWER_BOOL_PATTERN = re.compile(r"\b(and|or|not)\b")
_RESERVED_NAMES = {"And", "Or", "Not", "Implies", "If", "Abs", "True", "False"}


class _ExtractionPayload(TypedDict):
    args: list[str]
    return_type: str
    domain_constraints: list[str]
    postcondition: str
    confidence: str
    notes: str


def _to_str(value: object, default: str) -> str:
    return value if isinstance(value, str) else default


def _to_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _extract_signature_args(signature: str) -> list[str]:
    match = re.search(r"\((.*)\)", signature)
    if not match:
        return []
    raw_args = match.group(1).strip()
    if not raw_args:
        return []
    args: list[str] = []
    for chunk in raw_args.split(","):
        candidate = chunk.strip()
        if not candidate:
            continue
        name = candidate.split(":", 1)[0].strip()
        if name:
            args.append(name)
    return args


def _coerce_payload(
    payload: dict, allowed_args: list[str], return_type: str
) -> _ExtractionPayload:
    return {
        "args": allowed_args,
        "return_type": _to_str(payload.get("return_type"), return_type),
        "domain_constraints": _to_str_list(payload.get("domain_constraints")),
        "postcondition": _to_str(payload.get("postcondition"), "ret == ret"),
        "confidence": _to_str(payload.get("confidence"), "unknown"),
        "notes": _to_str(payload.get("notes"), ""),
    }


def _validate_expression(expr: str, allowed_names: set[str]) -> list[str]:
    errors: list[str] = []
    if _FORBIDDEN_EXPR_PATTERN.search(expr):
        errors.append("contains forbidden tokens")
    if _INFIX_BOOL_PATTERN.search(expr):
        errors.append("uses infix And/Or")
    if _LOWER_BOOL_PATTERN.search(expr):
        errors.append("uses python and/or/not")
    for token in _IDENTIFIER_PATTERN.findall(expr):
        if token in _RESERVED_NAMES:
            continue
        if token not in allowed_names:
            errors.append(f"unknown identifier `{token}`")
            break
    return errors


def _validate_payload(payload: _ExtractionPayload, allowed_args: list[str]) -> list[str]:
    errors: list[str] = []
    allowed_names = set(allowed_args) | {"ret"}

    if payload.get("args") != allowed_args:
        errors.append("args must exactly match signature arguments")

    postcondition = payload["postcondition"]
    if not postcondition.strip():
        errors.append("postcondition must be a non-empty string")
    else:
        post_errors = _validate_expression(postcondition, allowed_names)
        errors.extend([f"postcondition {item}" for item in post_errors])

    for constraint in payload["domain_constraints"]:
        constraint_errors = _validate_expression(constraint, allowed_names)
        errors.extend([f"domain constraint {item}" for item in constraint_errors])
    return errors


def _repair_payload(
    client: OllamaClient,
    payload: _ExtractionPayload,
    errors: list[str],
    signature: str,
    return_type: str,
) -> dict:
    repair_prompt = f"""
You must fix invalid JSON extraction output.

Return strict JSON with keys:
{{
  "args": ["..."],
  "return_type": "{return_type}",
  "domain_constraints": ["..."],
  "postcondition": "...",
  "confidence": "low|medium|high",
  "notes": "brief reasoning"
}}

Rules:
- args must match signature args exactly (same names/order), never include ret.
- postcondition must use only signature args and ret.
- domain_constraints/postcondition must not use: floor, sqrt, pow, **, //, lambda, [] or braces.
- Use only functional boolean ops: And(...), Or(...), Not(...), Implies(...).
- Never use infix And/Or or python and/or/not.
- domain_constraints must include only true input guards from code.

Signature:
{signature}

Errors to fix:
{json.dumps(errors, ensure_ascii=False)}

Current invalid JSON:
{json.dumps(payload, ensure_ascii=False)}
"""
    return client.generate_json(repair_prompt)


def extract_code_logic(
    client: OllamaClient,
    benchmark_id: str,
    signature: str,
    function_source: str,
    return_type: str,
    extra_context: str = "",
) -> ExtractionResult:
    prompt = f"""
You are extracting implementation semantics from Python function code.

Output strict JSON with keys:
{{
  "args": ["..."],
  "return_type": "{return_type}",
  "domain_constraints": ["..."],
  "postcondition": "...",
  "confidence": "low|medium|high",
  "notes": "brief reasoning"
}}

Rules:
- HARD CONSTRAINTS (MUST):
  1) `args` must contain ONLY signature arguments in the same order.
  2) `args` MUST NOT contain `ret`.
  3) `postcondition` MUST reference only signature args and `ret`.
  4) If forbidden tokens appear, rewrite before returning JSON.
- Capture actual behavior implied by code.
- Use Z3/Python-style expressions over args and ret.
- Allowed operators: And, Or, Not, Implies, If, ==, !=, <, <=, >, >=, +, -, *, /, %, Abs
- `ret` means return value.
- Use only argument names that appear in the provided signature.
- In formulas, allowed variable names are ONLY args and `ret`
  (no temporaries like `r`, `tmp`, `value`).
- If behavior depends on sorted input or other assumptions, include these in domain_constraints.
- Add domain constraints only from explicit checks/guards/assertions in code.
- Do not invent machine bounds or hidden assumptions (e.g., 32-bit ranges) unless explicit.
- Branch predicates used to split behavior (e.g., `x >= 0` vs `x < 0`) belong in postcondition,
  not in domain_constraints.
- Avoid contradictory or exhaustive branch conditions in domain_constraints.
- If code has no explicit guard/assert/raise for an argument, keep `domain_constraints` empty.
- Never output both sides of a split as constraints (forbidden: `x >= 0` and `x < 0` together).
- `domain_constraints` are only global input guards (assert/raise/precondition), not branch filters.
- Example forbidden in domain_constraints: `x % 2 == 0`.
- NEVER use Python boolean keywords `and`, `or`, `not`; use `And`, `Or`, `Not`.
- Use boolean combinators only in functional form:
  `And(...)`, `Or(...)`, `Not(...)`, `Implies(...)`.
- Do not use infix forms like `A Or B` or `A And B`.
- NEVER mix booleans into arithmetic (e.g., `a * (x > 0)` is forbidden).
- If `%` is used with denominator `d`, guard it with `d != 0`
  or encode with `If(d == 0, ..., expr_with_mod)`.
- For gcd-like behavior, include explicit edge-case logic for zero inputs
  and avoid undefined modulo situations.
- Postcondition must be a boolean formula over args and `ret`.
- Postcondition must be ONE valid expression (no semicolons, no multiple statements).
- For int return values, encode exact return mapping as `ret == ...` (use `If(...)` for branches).
- If code/docstring explicitly states "guarantees only ...", you MUST encode that weaker guarantee
  as postcondition (contract-style), even if exact branch mapping is possible.
- For bool return values, encode as `ret == (...)`.
- Do not weaken behavior to broad ranges (e.g., avoid `ret >= 0` if code is piecewise exact).
- Prefer exact branch-by-branch semantics from source.
- NEVER call the function name in formulas (forbidden: `foo(x)`); use only args and `ret`.
- Do not use `->`, `&&`, `||`, `>>`, `|`; use `Implies(...)`, `And(...)`, `Or(...)`.
- Do not use `=>`, `;`, commas as logical separators,
  chained comparisons like `a == b == c`, or names like `inf`.
- Do not use function names like `int(...)`, `floor(...)`, `sqrt(...)` in formulas.
- Forbidden tokens in formulas: `floor`, `sqrt`, `pow`,
  `**`, `//`, `lambda`, `[` and `]`, and any braces.
- If code computes integer square root, encode with constraints over `ret`, e.g.:
  `And(x >= 0, ret >= 0, ret * ret <= x, x < (ret + 1) * (ret + 1))`.
- Example forbidden: `ret == floor(sqrt(x))`
- Example allowed: `And(ret * ret <= x, x < (ret + 1) * (ret + 1))`
- Self-check before final JSON:
  - `args` excludes `ret`
  - No forbidden tokens in `domain_constraints` and `postcondition`
  - `postcondition` uses only args and `ret`

Examples:
- `ret == If(x == 0, 1, 0)`
- `ret == If(x > 0, 1, 0)`
- `ret == (x > 0)`

Signature:
{signature}

Function source:
{function_source}

Additional context:
{extra_context}
"""
    allowed_args = _extract_signature_args(signature)
    raw_payload = client.generate_json(prompt)
    payload = _coerce_payload(raw_payload, allowed_args, return_type)
    errors = _validate_payload(payload, allowed_args)
    if errors:
        repaired_raw = _repair_payload(
            client=client,
            payload=payload,
            errors=errors,
            signature=signature,
            return_type=return_type,
        )
        payload = _coerce_payload(repaired_raw, allowed_args, return_type)
        repair_errors = _validate_payload(payload, allowed_args)
        if repair_errors:
            payload["domain_constraints"] = []
            payload["postcondition"] = "ret == ret"
            payload["notes"] = "Auto-sanitized after validation failure."
            payload["confidence"] = "low"

    return ExtractionResult(
        benchmark_id=benchmark_id,
        args=payload["args"],
        return_type=payload["return_type"],
        domain_constraints=payload["domain_constraints"],
        postcondition=payload["postcondition"],
        confidence=payload["confidence"],
        notes=payload["notes"],
    )

