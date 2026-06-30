"""Tests for formal fingerprints and call-graph staleness detection."""

from __future__ import annotations

from dualify.fingerprint import (
    FRESH,
    STALE_DEPENDENCY,
    STALE_FUNCTION,
    build_call_graph,
    classify_staleness,
    compute_fingerprint,
)
from dualify.types import BenchmarkCase


def _case(
    *,
    qualname: str,
    source: str,
    spec: str = "does a thing",
    signature: str | None = None,
    arg_types: dict[str, str] | None = None,
    file: str = "m.py",
) -> BenchmarkCase:
    return BenchmarkCase(
        benchmark_id=qualname,
        file=file,
        qualname=qualname,
        lineno=1,
        signature=signature or f"{qualname}(x: int) -> int",
        arg_types=arg_types or {"x": "int"},
        return_type="int",
        informal_spec=spec,
        extra_context="",
        function_source=source,
    )


def test_compute_fingerprint_is_input_sensitive() -> None:
    a = compute_fingerprint(_case(qualname="f", source="def f(x):\n    return x + 1"))
    b = compute_fingerprint(_case(qualname="f", source="def f(x):\n    return x + 2"))
    assert a["source_sha256"] != b["source_sha256"]
    # Spec change moves spec hash but not source hash.
    c = compute_fingerprint(
        _case(qualname="f", source="def f(x):\n    return x + 1", spec="different spec")
    )
    assert c["source_sha256"] == a["source_sha256"]
    assert c["spec_sha256"] != a["spec_sha256"]


def test_build_call_graph_resolves_local_calls() -> None:
    helper = _case(qualname="helper", source="def helper(x):\n    return x + 1")
    main = _case(qualname="main", source="def main(x):\n    return helper(x) + 1")
    graph = build_call_graph([helper, main])
    assert graph["main"] == ["helper"]
    assert graph["helper"] == []


def test_classify_staleness_marks_changed_and_callers() -> None:
    helper_v1 = _case(qualname="helper", source="def helper(x):\n    return x + 1")
    main = _case(qualname="main", source="def main(x):\n    return helper(x) + 1")
    leaf = _case(qualname="leaf", source="def leaf(x):\n    return x * 2")

    previous = {
        "helper": compute_fingerprint(helper_v1),
        "main": compute_fingerprint(main),
        "leaf": compute_fingerprint(leaf),
    }

    # helper's body changes; main calls helper; leaf is independent.
    helper_v2 = _case(qualname="helper", source="def helper(x):\n    return x + 99")
    classes = classify_staleness(previous, [helper_v2, main, leaf])
    assert classes["helper"] == STALE_FUNCTION
    assert classes["main"] == STALE_DEPENDENCY
    assert classes["leaf"] == FRESH


def test_classify_staleness_all_fresh_when_unchanged() -> None:
    helper = _case(qualname="helper", source="def helper(x):\n    return x + 1")
    main = _case(qualname="main", source="def main(x):\n    return helper(x) + 1")
    previous = {
        "helper": compute_fingerprint(helper),
        "main": compute_fingerprint(main),
    }
    classes = classify_staleness(previous, [helper, main])
    assert classes == {"helper": FRESH, "main": FRESH}


def test_unseen_function_is_stale_function() -> None:
    main = _case(qualname="main", source="def main(x):\n    return x + 1")
    classes = classify_staleness({}, [main])
    assert classes["main"] == STALE_FUNCTION
