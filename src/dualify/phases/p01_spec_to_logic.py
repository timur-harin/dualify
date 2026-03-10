from dualify.ollama_client import OllamaClient
from dualify.types import ExtractionResult


def extract_spec_logic(
    client: OllamaClient,
    benchmark_id: str,
    signature: str,
    informal_spec: str,
    return_type: str,
    extra_context: str = "",
) -> ExtractionResult:
    prompt = f"""
You are translating an informal function spec into a logical formula.

Task:
- infer argument names from signature
- infer domain constraints
- infer postcondition over args and ret

Output strict JSON with keys:
{{
  "args": ["..."],
  "return_type": "{return_type}",
  "domain_constraints": ["..."],
  "postcondition": "...",
  "confidence": "low|medium|high",
  "notes": "short explanation"
}}

Rules:
- Use Z3/Python-style expressions.
- Allowed boolean/int operators: And, Or, Not, Implies, If, ==, !=, <, <=, >, >=, +, -, *, /, %, Abs
- `ret` means the return value.
- Use only argument names that appear in the provided signature.
- Keep expressions compact and deterministic.
- NEVER use Python boolean keywords `and`, `or`, `not`; use `And`, `Or`, `Not`.
- NEVER mix booleans into arithmetic (e.g., `a * (x > 0)` is forbidden).
- If `%` is used with denominator `d`, guard it with `d != 0`
  or encode with `If(d == 0, ..., expr_with_mod)`.
- For gcd-like specs, make edge cases explicit (e.g., `a == 0`
  or `b == 0`) and avoid undefined modulo situations.
- Postcondition must be a boolean formula over args and `ret`.
- Postcondition must be ONE valid expression (no semicolons, no multiple statements).
- For int return values, write exact mapping with `ret == ...` (often with `If(...)`).
- For bool return values, write `ret == (...)`.
- Encode piecewise behavior explicitly:
  `If(cond, expr1, expr2)` or `And(Implies(...), Implies(...))`.
- Do not weaken semantics. The formula must describe exact behavior, not just range/properties.
- NEVER call the function name in formulas (forbidden: `foo(x)`); use only args and `ret`.
- Do not use `->`, `&&`, `||`, `>>`, `|`; use `Implies(...)`, `And(...)`, `Or(...)`.
- Do not use `=>`, `;`, commas as logical separators,
  chained comparisons like `a == b == c`, or names like `inf`.

Examples:
- int flag: `ret == If(x == 0, 1, 0)`
- bool predicate: `ret == (x > 0)`
- piecewise int: `ret == If(x > 0, 1, 0)`

Signature:
{signature}

Informal specification:
{informal_spec}

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

