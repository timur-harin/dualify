from pathlib import Path

from dualify.discovery import discover_python_cases


def test_discover_synthetic_cases() -> None:
    root = Path(__file__).resolve().parents[1]
    cases = discover_python_cases(root / "benchmark" / "synthetic", root)
    ids = {case.benchmark_id for case in cases}
    assert {"max_of_two", "is_positive", "sum_range", "is_sorted", "gcd", "binary_search"} <= ids

