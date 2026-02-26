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
- NEVER use Python boolean keywords `and`, `or`, `not`; use `And`, `Or`, `Not`.
- NEVER mix booleans into arithmetic (e.g., `a * (x > 0)` is forbidden).
- If `%` is used with denominator `d`, guard it with `d != 0`
  or encode with `If(d == 0, ..., expr_with_mod)`.
- For gcd-like behavior, include explicit edge-case logic for zero inputs
  and avoid undefined modulo situations.
- Postcondition must be a boolean formula over args and `ret`.
- NEVER call the function name in formulas (forbidden: `foo(x)`); use only args and `ret`.
- Do not use `->`, `&&`, `||`, `>>`, `|`; use `Implies(...)`, `And(...)`, `Or(...)`.

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

