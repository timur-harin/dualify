from dualify.phases.p01_spec_to_logic import _post_quality_issues as spec_post_quality_issues
from dualify.phases.p02_code_to_logic import _post_quality_issues as code_post_quality_issues


def test_post_quality_rejects_tautological_ret_self() -> None:
    assert "must not be tautology `ret == ret`" in spec_post_quality_issues("ret == ret")
    assert "must not be tautology `ret == ret`" in code_post_quality_issues("ret == ret")


def test_post_quality_rejects_quantifier_assigned_to_ret() -> None:
    expr = "ret == ForAll([i], i >= 0)"
    assert "must not assign quantifier directly to ret" in spec_post_quality_issues(expr)
    assert "must not assign quantifier directly to ret" in code_post_quality_issues(expr)
