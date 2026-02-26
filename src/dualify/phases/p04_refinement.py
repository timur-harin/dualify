from dualify.ollama_client import OllamaClient
from dualify.types import SmtResult


def build_refinement(
    client: OllamaClient,
    benchmark_id: str,
    signature: str,
    informal_spec: str,
    function_source: str,
    spec_postcondition: str,
    code_postcondition: str,
    smt_result: SmtResult,
) -> dict:
    counterexample = smt_result.counterexample or {}
    prompt = f"""
You are a verification assistant. We found a mismatch between spec and implementation.

Return strict JSON:
{{
  "benchmark_id": "{benchmark_id}",
  "status": "needs_spec_refinement|needs_code_fix|unclear",
  "spec_action": "what to clarify in informal spec",
  "code_action": "what to fix in code",
  "question_to_developer": "single concrete question",
  "rationale": "short reason"
}}

Signature:
{signature}

Informal spec:
{informal_spec}

Function source:
{function_source}

Spec postcondition:
{spec_postcondition}

Code postcondition:
{code_postcondition}

Counterexample:
{counterexample}
"""
    payload = client.generate_json(prompt, temperature=0.1)
    return payload

