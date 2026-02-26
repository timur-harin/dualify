from dualify.types import ExtractionResult


def get_fallback_extraction(benchmark_id: str) -> ExtractionResult:
    if benchmark_id == "max_of_two":
        return ExtractionResult(
            benchmark_id=benchmark_id,
            args=["a", "b"],
            return_type="int",
            domain_constraints=[],
            postcondition="ret == If(a >= b, a, b)",
            confidence="fallback",
            notes="Deterministic fallback formula.",
        )
    if benchmark_id == "is_positive":
        return ExtractionResult(
            benchmark_id=benchmark_id,
            args=["x"],
            return_type="bool",
            domain_constraints=[],
            postcondition="ret == (x > 0)",
            confidence="fallback",
            notes="Deterministic fallback formula.",
        )
    if benchmark_id == "sum_range":
        return ExtractionResult(
            benchmark_id=benchmark_id,
            args=["n"],
            return_type="int",
            domain_constraints=[],
            postcondition="ret == If(n <= 0, 0, (n * (n + 1)) / 2)",
            confidence="fallback",
            notes="Deterministic fallback formula.",
        )
    if benchmark_id == "is_sorted":
        return ExtractionResult(
            benchmark_id=benchmark_id,
            args=["a0", "a1", "a2", "a3"],
            return_type="bool",
            domain_constraints=[],
            postcondition="ret == And(a0 <= a1, a1 <= a2, a2 <= a3)",
            confidence="fallback",
            notes="Deterministic fallback formula for bounded array.",
        )
    if benchmark_id == "gcd":
        return ExtractionResult(
            benchmark_id=benchmark_id,
            args=["a", "b"],
            return_type="int",
            domain_constraints=["Not(And(a == 0, b == 0))"],
            postcondition="And(ret > 0, a % ret == 0, b % ret == 0)",
            confidence="fallback",
            notes="Weak gcd approximation without quantifiers.",
        )
    if benchmark_id == "binary_search":
        return ExtractionResult(
            benchmark_id=benchmark_id,
            args=["a0", "a1", "a2", "a3", "target"],
            return_type="int",
            domain_constraints=["And(a0 < a1, a1 < a2, a2 < a3)"],
            postcondition=(
                "ret == If(target == a1, 1, "
                "If(target == a0, 0, If(target == a2, 2, If(target == a3, 3, -1))))"
            ),
            confidence="fallback",
            notes="Deterministic fallback formula for bounded array.",
        )
    raise ValueError(f"No fallback for benchmark {benchmark_id}")

