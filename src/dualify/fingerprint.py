"""Formal fingerprints and staleness detection for Dualify runs.

A *formal fingerprint* is the durable per-function record Dualify persists so
an outer agent (or a reviewer) can tell, without re-running the LLM, whether a
stored verdict still describes the current code. Earlier versions persisted
the extracted formulas, witnesses, and case labels but **no checksum of the
inputs**, so "is this record still valid?" could not be answered mechanically.

This module closes that gap. It hashes the three inputs that fully determine an
extraction -- the function source, the informal spec (plus extra context), and
the signature/argument types -- together with the prompt-template and tool
versions that produced the formulas. A stored fingerprint is therefore
invalidated exactly when one of those inputs changes.

Staleness is defined over the call graph, not the whole repository:

* ``fresh``            -- source, spec, signature, and versions all match.
* ``stale_function``   -- this function's own source/spec/signature changed,
                          or the extractor/prompt version changed.
* ``stale_dependency`` -- this function is unchanged, but a function it calls
                          (transitively) is ``stale_function``; its contract
                          may rely on a callee whose behavior moved.

This is deliberately *not* "everything goes stale on every commit": a commit
that touches one function invalidates that function and its transitive
callers, leaving the rest of the cached fingerprints reusable.
"""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Iterable

from dualify.types import BenchmarkCase

# Bump when the fingerprint *schema* changes (added/removed hashed inputs).
FINGERPRINT_VERSION = 1

# Bump when prompt templates or the parser/normalizer change in a way that can
# alter extracted formulas; a fingerprint recorded under an older value is then
# treated as stale even if the inputs are byte-identical.
EXTRACTOR_VERSION = "p01p02-2026.06-r2"

FRESH = "fresh"
STALE_FUNCTION = "stale_function"
STALE_DEPENDENCY = "stale_dependency"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _arg_types_signature(arg_types: dict[str, str]) -> str:
    return ";".join(f"{name}:{arg_types[name]}" for name in sorted(arg_types))


def compute_fingerprint(case: BenchmarkCase) -> dict[str, object]:
    """Return the formal-fingerprint header for one function.

    The hashes uniquely determine what the extractor saw. ``spec_sha256``
    folds in ``extra_context`` because class docstrings / ``__init__`` bodies
    are part of what ``p01`` reads.
    """
    spec_material = case.informal_spec + "\x1f" + case.extra_context
    signature_material = case.signature + "\x1f" + _arg_types_signature(case.arg_types)
    return {
        "fingerprint_version": FINGERPRINT_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
        "source_sha256": _sha256(case.function_source),
        "spec_sha256": _sha256(spec_material),
        "signature_sha256": _sha256(signature_material),
        "return_type": case.return_type,
        "arg_types": dict(case.arg_types),
    }


def _called_names(function_source: str) -> list[str]:
    try:
        module = ast.parse(function_source)
    except SyntaxError:
        return []
    seen: set[str] = set()
    names: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names


def build_call_graph(cases: Iterable[BenchmarkCase]) -> dict[str, list[str]]:
    """Map each case ``benchmark_id`` to the ``benchmark_id``s it calls.

    Call targets are resolved by short function name (the tail of the
    qualname); a call resolves to a same-file definition when one exists,
    otherwise to any case defining that name. Unresolved calls (library
    functions, builtins) are dropped.
    """
    cases = list(cases)
    by_id = {case.benchmark_id: case for case in cases}
    name_to_ids: dict[str, list[str]] = {}
    for case in cases:
        short = case.qualname.split(".")[-1]
        name_to_ids.setdefault(short, []).append(case.benchmark_id)

    graph: dict[str, list[str]] = {}
    for case in cases:
        targets: list[str] = []
        for called in _called_names(case.function_source):
            candidates = name_to_ids.get(called, [])
            if not candidates:
                continue
            same_file = [cid for cid in candidates if by_id[cid].file == case.file]
            target = (same_file or candidates)[0]
            if target != case.benchmark_id and target not in targets:
                targets.append(target)
        graph[case.benchmark_id] = targets
    return graph


def _transitive_callers(
    changed: set[str],
    call_graph: dict[str, list[str]],
) -> set[str]:
    """Return every node that can reach a changed node through callee edges."""
    callers_of: dict[str, set[str]] = {node: set() for node in call_graph}
    for caller, callees in call_graph.items():
        for callee in callees:
            callers_of.setdefault(callee, set()).add(caller)

    impacted: set[str] = set()
    frontier = list(changed)
    while frontier:
        node = frontier.pop()
        for caller in callers_of.get(node, set()):
            if caller not in impacted:
                impacted.add(caller)
                frontier.append(caller)
    return impacted


def fingerprints_match(previous: dict[str, object], current: dict[str, object]) -> bool:
    keys = (
        "fingerprint_version",
        "extractor_version",
        "source_sha256",
        "spec_sha256",
        "signature_sha256",
    )
    return all(previous.get(key) == current.get(key) for key in keys)


def classify_staleness(
    previous_fingerprints: dict[str, dict[str, object]],
    cases: Iterable[BenchmarkCase],
) -> dict[str, str]:
    """Classify each current case as fresh / stale_function / stale_dependency.

    ``previous_fingerprints`` maps ``benchmark_id`` -> a fingerprint header as
    produced by :func:`compute_fingerprint` (e.g. read from a prior run's
    JSON). A case with no prior fingerprint is ``stale_function`` (never seen).
    """
    cases = list(cases)
    current = {case.benchmark_id: compute_fingerprint(case) for case in cases}
    call_graph = build_call_graph(cases)

    directly_changed: set[str] = set()
    for benchmark_id, fp in current.items():
        prior = previous_fingerprints.get(benchmark_id)
        if prior is None or not fingerprints_match(prior, fp):
            directly_changed.add(benchmark_id)

    impacted = _transitive_callers(directly_changed, call_graph)

    result: dict[str, str] = {}
    for benchmark_id in current:
        if benchmark_id in directly_changed:
            result[benchmark_id] = STALE_FUNCTION
        elif benchmark_id in impacted:
            result[benchmark_id] = STALE_DEPENDENCY
        else:
            result[benchmark_id] = FRESH
    return result
