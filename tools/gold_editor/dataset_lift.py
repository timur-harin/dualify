"""Strip embedded formulas from informal specs and lift them toward the Dualify fragment.

Two responsibilities, both pure:

1. ``strip_formal_lines(text)`` -- remove PEP316-style ``pre:`` / ``post:`` /
   ``post[...]:`` / ``raises:`` directives (and their indented continuations)
   from a docstring, leaving only the prose. Returns ``(clean, stripped)``
   where ``stripped`` is the raw text of each directive that was removed.

2. ``lift_to_fragment(expr)`` -- best-effort rewrite of dataset-style
   formulas into the Dualify fragment: ``__return__`` -> ``ret``,
   ``result`` -> ``ret`` (PEP316 / icontract conventions), ``implies(...)``
   -> ``Implies(...)``. Anything else (Python ``and``/``or``/``not``,
   comprehensions, tuple equality) is left alone for the validator to flag
   and the operator to rewrite by hand.

Tested via ``python tools/gold_editor/dataset_lift.py``.
"""

from __future__ import annotations

import ast
import re

_DIRECTIVE_RE = re.compile(r"^\s*(pre|post(?:\[[^\]]*\])?|raises)\s*:", re.IGNORECASE)
_METADATA_NOTE_RE = re.compile(r"^\s*(NOTE|TODO|FIXME|NB|XXX|WARNING|HACK|TBD)\s*:", re.IGNORECASE)


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _strip_by(text: str, head_re: re.Pattern[str]) -> tuple[str, list[str]]:
    """Drop blocks whose header matches ``head_re``, plus any indented continuations."""
    if not text:
        return text, []
    lines = text.splitlines()
    kept: list[str] = []
    stripped: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not head_re.match(line):
            kept.append(line)
            i += 1
            continue
        header_indent = _line_indent(line)
        block = [line]
        i += 1
        while i < len(lines):
            nxt = lines[i]
            if not nxt.strip():
                break
            if _line_indent(nxt) <= header_indent:
                break
            block.append(nxt)
            i += 1
        stripped.append("\n".join(block))
    out = "\n".join(kept)
    out = re.sub(r"\n{3,}", "\n\n", out).strip("\n")
    return out, stripped


def strip_formal_lines(text: str) -> tuple[str, list[str]]:
    """Drop ``pre:`` / ``post:`` / ``raises:`` directives (with continuations)."""
    return _strip_by(text, _DIRECTIVE_RE)


def strip_metadata_notes(text: str) -> tuple[str, list[str]]:
    """Drop ``NOTE:`` / ``TODO:`` / ``FIXME:`` / ``NB:`` / ... lines (with continuations).

    These mark commentary about the example itself (e.g. "NOTE: this is an
    example of contracts on recursive functions") rather than describing what
    the function does, and are useless as informal specs.
    """
    return _strip_by(text, _METADATA_NOTE_RE)


_IDENT_REWRITES = {
    "__return__": "ret",  # PEP316 / crosshair
    "_": "ret",  # PEP316 anonymous return-value alias
    "result": "ret",  # icontract
    "implies": "Implies",
}


class _CollectionQuantifierLifter(ast.NodeTransformer):
    """Rewrite ``all(P for x in C)`` / ``any(P for x in C)`` into ForAll/Exists.

    Handles single-generator forms with either a single binder
    (``for x in C``) or a tuple binder (``for i, j in C``). The bound names
    are substituted with index-access expressions ``C[_k][n]`` so the body
    no longer references the comprehension binders. Fresh ``_k0``, ``_k1``,
    ... indices are minted to avoid collisions on nested quantifiers.

    Filters (``for x in C if Q``), multi-generator forms, and async
    comprehensions are left alone -- the live validator will then surface
    them to the operator.
    """

    def __init__(self) -> None:
        super().__init__()
        self._counter = 0

    def _fresh_index(self) -> str:
        name = f"_k{self._counter}"
        self._counter += 1
        return name

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if not (isinstance(node.func, ast.Name) and node.func.id in {"all", "any"}):
            return node
        if len(node.args) != 1 or node.keywords:
            return node
        gen = node.args[0]
        if not isinstance(gen, ast.GeneratorExp):
            return node
        if len(gen.generators) != 1:
            return node
        comp = gen.generators[0]
        if comp.ifs or getattr(comp, "is_async", 0):
            return node

        target = comp.target
        iterable = comp.iter
        idx_name = self._fresh_index()
        idx_node = ast.Name(id=idx_name, ctx=ast.Load())
        element_expr = ast.Subscript(value=iterable, slice=idx_node, ctx=ast.Load())

        mapping = self._build_substitution(target, element_expr)
        if mapping is None:
            return node
        body = _NameSubstituter(mapping).visit(gen.elt)

        range_expr = ast.Call(
            func=ast.Name(id="And", ctx=ast.Load()),
            args=[
                ast.Compare(
                    left=ast.Constant(value=0),
                    ops=[ast.LtE()],
                    comparators=[idx_node],
                ),
                ast.Compare(
                    left=idx_node,
                    ops=[ast.Lt()],
                    comparators=[
                        ast.Call(
                            func=ast.Name(id="Length", ctx=ast.Load()),
                            args=[iterable],
                            keywords=[],
                        )
                    ],
                ),
            ],
            keywords=[],
        )

        if node.func.id == "all":
            inner = ast.Call(
                func=ast.Name(id="Implies", ctx=ast.Load()),
                args=[range_expr, body],
                keywords=[],
            )
            head = "ForAll"
        else:
            inner = ast.Call(
                func=ast.Name(id="And", ctx=ast.Load()),
                args=[range_expr, body],
                keywords=[],
            )
            head = "Exists"
        return ast.Call(
            func=ast.Name(id=head, ctx=ast.Load()),
            args=[ast.List(elts=[idx_node], ctx=ast.Load()), inner],
            keywords=[],
        )

    @staticmethod
    def _build_substitution(target: ast.expr, element_expr: ast.expr) -> dict[str, ast.expr] | None:
        if isinstance(target, ast.Name):
            return {target.id: element_expr}
        if isinstance(target, ast.Tuple):
            mapping: dict[str, ast.expr] = {}
            for i, el in enumerate(target.elts):
                if not isinstance(el, ast.Name):
                    return None
                mapping[el.id] = ast.Subscript(
                    value=element_expr,
                    slice=ast.Constant(value=i),
                    ctx=ast.Load(),
                )
            return mapping
        return None


class _NameSubstituter(ast.NodeTransformer):
    def __init__(self, mapping: dict[str, ast.expr]) -> None:
        super().__init__()
        self._mapping = mapping

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if node.id in self._mapping:
            return self._mapping[node.id]
        return node


def _lift_collection_quantifiers(expr: str) -> str:
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return expr
    transformed = _CollectionQuantifierLifter().visit(tree)
    ast.fix_missing_locations(transformed)
    try:
        return ast.unparse(transformed)
    except Exception:
        return expr


def lift_to_fragment(expr: str) -> str:
    """Best-effort rewrite of a dataset formula into the Dualify fragment.

    Two passes:
    1. Structural: rewrite ``all(P for x in C)`` into
       ``ForAll([_k], Implies(0 <= _k < Length(C), P[x↦C[_k]]))`` and
       ``any(P for x in C)`` into
       ``Exists([_k], And(0 <= _k < Length(C), P[x↦C[_k]]))``.
    2. Word-boundary identifier substitutions (``__return__`` -> ``ret``,
       ``result`` -> ``ret``, ``implies`` -> ``Implies``, ``_`` -> ``ret``).

    Anything else (multi-generator comprehensions, ``and``/``or``/``not``,
    ``in`` / ``not in`` comparisons, tuple equality, etc.) is left alone so
    the live validator surfaces it to the operator.
    """
    if not expr:
        return expr
    out = _lift_collection_quantifiers(expr)
    for src, dst in _IDENT_REWRITES.items():
        out = re.sub(rf"\b{re.escape(src)}\b", dst, out)
    return out


def _selftest() -> None:
    chess_doc = (
        "Determine whether this piece can move to the given position (in a single turn).\n"
        "\n"
        "pre: (0 <= x < 8) and (0 <= y < 8)\n"
        "\n"
        '#  It\'s never valid to "move" to your present location:\n'
        "post: implies((x, y) == (self.x, self.y), not __return__)"
    )
    clean, stripped = strip_formal_lines(chess_doc)
    assert "pre:" not in clean, clean
    assert "post:" not in clean, clean
    assert "Determine whether this piece" in clean, clean
    assert "It's never valid" in clean, clean
    assert len(stripped) == 2, stripped

    multiline_doc = "Header line.\n\npre: x > 0\n    and x < 100\n\ntail prose."
    clean2, stripped2 = strip_formal_lines(multiline_doc)
    assert "pre:" not in clean2
    assert "tail prose." in clean2
    assert "x > 0" in stripped2[0] and "x < 100" in stripped2[0]

    icontract_doc = "Compute the histogram of jolt differences in ``adapters``."
    clean3, stripped3 = strip_formal_lines(icontract_doc)
    assert clean3 == icontract_doc
    assert stripped3 == []

    note_only = "NOTE: This is an example of contracts on recursive functions."
    clean4, stripped4 = strip_metadata_notes(note_only)
    assert clean4 == "", clean4
    assert len(stripped4) == 1

    note_with_continuation = (
        "NOTE: To perform additional testing,\n    you can write extra helpers.\n"
        "\nFind the smallest element."
    )
    clean5, stripped5 = strip_metadata_notes(note_with_continuation)
    assert "Find the smallest element." in clean5
    assert "NOTE:" not in clean5
    assert "additional testing" in stripped5[0]

    assert lift_to_fragment("implies(__return__, hash(self) == hash(other))") == (
        "Implies(ret, hash(self) == hash(other))"
    )
    assert lift_to_fragment("result + 1 == len(adapters)") == "ret + 1 == len(adapters)"
    assert lift_to_fragment("results") == "results", "no substring match"
    assert lift_to_fragment("__return__ != 'moo'") == "ret != 'moo'"
    assert lift_to_fragment("_ != 42") == "ret != 42"
    assert lift_to_fragment("foo_bar + _") == "foo_bar + ret"
    # Don't munge non-anonymous underscores.
    assert lift_to_fragment("__init__") == "__init__"
    assert lift_to_fragment("foo_bar") == "foo_bar"

    # Collection quantifier lifting.
    single = lift_to_fragment("all((x > 0 for x in ret))")
    assert "ForAll" in single and "Implies" in single and "Length(ret)" in single, single
    assert "ret[_k0]" in single, single

    tup = lift_to_fragment("all((0 <= i <= h and 0 <= j <= w for i, j in ret))")
    assert "ForAll" in tup and "ret[_k0][0]" in tup and "ret[_k0][1]" in tup, tup

    any_form = lift_to_fragment("any((x == 0 for x in xs))")
    assert any_form.startswith("Exists") and "And" in any_form, any_form

    # Multiple quantifiers in one formula get unique indices.
    nested_two = lift_to_fragment("all((x > 0 for x in a)) and any((y == 0 for y in b))")
    assert "_k0" in nested_two and "_k1" in nested_two, nested_two

    # Filters / multi-generator forms are deliberately left alone.
    skip_filter = lift_to_fragment("all((x > 0 for x in xs if x != y))")
    assert "for x in xs if" in skip_filter, skip_filter

    print("dataset_lift self-tests: OK")


if __name__ == "__main__":
    _selftest()
