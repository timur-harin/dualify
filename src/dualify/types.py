from dataclasses import dataclass


@dataclass
class BenchmarkCase:
    benchmark_id: str
    file: str
    signature: str
    arg_types: dict[str, str]
    return_type: str
    informal_spec: str
    extra_context: str
    function_source: str


@dataclass
class ExtractionResult:
    benchmark_id: str
    args: list[str]
    return_type: str
    domain_constraints: list[str]
    postcondition: str
    confidence: str
    notes: str


@dataclass
class SmtResult:
    benchmark_id: str
    equivalent: bool
    reason: str
    counterexample: dict[str, int | bool] | None
    diagnostics: dict[str, object] | None = None

