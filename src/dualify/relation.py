"""Predicate-strength lattice between a generated contract and a reference.

Z3 equivalence alone hides *direction*: a generated postcondition can be
logically stronger (more guarantees, risk of invented constraints), weaker
(under-specification), equivalent, or incomparable to the gold reference. This
module reports that direction for preconditions and postconditions separately,
following the predicate-lattice framing (Dijkstra; weakest-precondition /
strongest-postcondition) recommended for the evaluation.

Conventions (relative to the *generated* contract):

* ``equivalent``          -- gen <=> ref
* ``generated_stronger``  -- gen => ref but not conversely
                             (pre: narrower input domain; post: more guarantees)
* ``generated_weaker``    -- ref => gen but not conversely
* ``incomparable``        -- neither direction holds
* ``undetermined``        -- Z3 returned ``unknown`` on a needed implication
* ``parse_error``         -- a formula could not be evaluated
"""

from __future__ import annotations

from typing import Any

import z3

from dualify.phases.p03_smt_checking import (
    _SOLVER_TIMEOUT_MS,
    CaseSpec,
    _augment_scope_from_formulas,
    _canonicalize_expression,
    _make_var,
    _safe_eval,
)
from dualify.types import ExtractionResult

EQUIVALENT = "equivalent"
GENERATED_STRONGER = "generated_stronger"
GENERATED_WEAKER = "generated_weaker"
INCOMPARABLE = "incomparable"
UNDETERMINED = "undetermined"
PARSE_ERROR = "parse_error"


def _implies(hypothesis: Any, conclusion: Any) -> bool | None:
    """Return True if ``hypothesis => conclusion`` is valid, None on unknown."""
    solver = z3.Solver()
    solver.set("timeout", _SOLVER_TIMEOUT_MS)
    solver.add(z3.And(hypothesis, z3.Not(conclusion)))
    status = solver.check()
    if status == z3.unsat:
        return True
    if status == z3.sat:
        return False
    return None


def _relation_from_directions(gen_implies_ref: bool | None, ref_implies_gen: bool | None) -> str:
    if gen_implies_ref is None or ref_implies_gen is None:
        return UNDETERMINED
    if gen_implies_ref and ref_implies_gen:
        return EQUIVALENT
    if gen_implies_ref and not ref_implies_gen:
        return GENERATED_STRONGER
    if ref_implies_gen and not gen_implies_ref:
        return GENERATED_WEAKER
    return INCOMPARABLE


def contract_relation(
    case_spec: CaseSpec,
    gold: ExtractionResult,
    generated: ExtractionResult,
) -> dict[str, str]:
    """Classify pre and post relations of *generated* against *gold*.

    Preconditions are compared as conjunctions over the whole input space.
    Postconditions are compared on the common precondition domain
    (``And(pre_gold, pre_gen)``), matching the cross-check semantics.
    """
    scope: dict[str, Any] = {}
    known: set[str] = set()
    for arg, type_name in case_spec.arg_types.items():
        scope[arg] = _make_var(arg, type_name)
        known.add(arg)
    scope["ret"] = _make_var("ret", case_spec.return_type)
    known.add("ret")

    bid = case_spec.benchmark_id

    def canon(expr: str) -> str:
        return _canonicalize_expression(expr, bid)

    try:
        gold_pre = [canon(c) for c in gold.domain_constraints]
        gen_pre = [canon(c) for c in generated.domain_constraints]
        gold_post = canon(gold.postcondition)
        gen_post = canon(generated.postcondition)
        _augment_scope_from_formulas(
            scope, known, [*gold_pre, *gen_pre, gold_post, gen_post]
        )
        gold_pre_z = [_safe_eval(c, scope, bid) for c in gold_pre]
        gen_pre_z = [_safe_eval(c, scope, bid) for c in gen_pre]
        gold_post_z = _safe_eval(gold_post, scope, bid)
        gen_post_z = _safe_eval(gen_post, scope, bid)
    except Exception:
        return {"pre": PARSE_ERROR, "post": PARSE_ERROR}

    gold_pre_and = z3.And(*gold_pre_z) if gold_pre_z else z3.BoolVal(True)
    gen_pre_and = z3.And(*gen_pre_z) if gen_pre_z else z3.BoolVal(True)

    pre_relation = _relation_from_directions(
        _implies(gen_pre_and, gold_pre_and),
        _implies(gold_pre_and, gen_pre_and),
    )

    common_pre = z3.And(gold_pre_and, gen_pre_and)
    post_relation = _relation_from_directions(
        _implies(z3.And(common_pre, gen_post_z), gold_post_z),
        _implies(z3.And(common_pre, gold_post_z), gen_post_z),
    )

    return {"pre": pre_relation, "post": post_relation}
