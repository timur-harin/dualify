from dualify.ollama_client import OllamaClient
from dualify.types import ExtractionResult


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
- Capture actual behavior implied by code.
- Use Z3/Python-style expressions over args and ret.
- Allowed operators: And, Or, Not, Implies, If, ==, !=, <, <=, >, >=, +, -, *, /, %, Abs
- `ret` means return value.
- Use only argument names that appear in the provided signature.
- If behavior depends on sorted input or other assumptions, include these in domain_constraints.
- Add domain constraints only from explicit checks/guards/assertions in code.
- Do not invent machine bounds or hidden assumptions (e.g., 32-bit ranges) unless explicit.
- Branch predicates used to split behavior (e.g., `x >= 0` vs `x < 0`) belong in postcondition,
  not in domain_constraints.
- Avoid contradictory or exhaustive branch conditions in domain_constraints.
- NEVER use Python boolean keywords `and`, `or`, `not`; use `And`, `Or`, `Not`.
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
    payload = client.generate_json(prompt)
    return ExtractionResult(
        benchmark_id=benchmark_id,
        args=payload["args"],
        return_type=payload["return_type"],
        domain_constraints=payload.get("domain_constraints", []),
        postcondition=payload["postcondition"],
        confidence=payload.get("confidence", "unknown"),
        notes=payload.get("notes", ""),
    )

