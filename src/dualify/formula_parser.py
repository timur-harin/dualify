import ast
import re
from collections.abc import Callable

_RET_TOKEN = re.compile(r"\bret\b")


class _NormalizeTransformer(ast.NodeTransformer):
    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.value, ast.Name):
            return ast.copy_location(
                ast.Name(id=f"{node.value.id}_{node.attr}", ctx=ast.Load()),
                node,
            )
        return node

    def _membership_for_tuple_unit(self, seq: ast.expr, elements: list[ast.expr]) -> ast.expr:
        idx = ast.Name(id="_idx", ctx=ast.Load())
        bounds = ast.Call(
            func=ast.Name(id="And", ctx=ast.Load()),
            args=[
                ast.Compare(
                    left=ast.Constant(value=0),
                    ops=[ast.LtE()],
                    comparators=[idx],
                ),
                ast.Compare(
                    left=idx,
                    ops=[ast.Lt()],
                    comparators=[
                        ast.Call(
                            func=ast.Name(id="Length", ctx=ast.Load()),
                            args=[seq],
                            keywords=[],
                        )
                    ],
                ),
            ],
            keywords=[],
        )
        conjuncts: list[ast.expr] = [bounds]
        for pos, element in enumerate(elements):
            conjuncts.append(
                ast.Compare(
                    left=ast.Subscript(
                        value=ast.Subscript(
                            value=seq,
                            slice=idx,
                            ctx=ast.Load(),
                        ),
                        slice=ast.Constant(value=pos),
                        ctx=ast.Load(),
                    ),
                    ops=[ast.Eq()],
                    comparators=[element],
                )
            )
        body = conjuncts[0]
        for conjunct in conjuncts[1:]:
            body = ast.Call(
                func=ast.Name(id="And", ctx=ast.Load()),
                args=[body, conjunct],
                keywords=[],
            )
        return ast.Call(
            func=ast.Name(id="Exists", ctx=ast.Load()),
            args=[ast.List(elts=[idx], ctx=ast.Load()), body],
            keywords=[],
        )

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if (
            isinstance(node.func, ast.Name)
            and node.func.id in {"And", "Or"}
            and len(node.args) == 1
        ):
            return ast.copy_location(node.args[0], node)
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "Contains"
            and len(node.args) == 2
            and isinstance(node.args[1], ast.Call)
            and isinstance(node.args[1].func, ast.Name)
            and node.args[1].func.id == "Unit"
            and len(node.args[1].args) == 1
            and isinstance(node.args[1].args[0], ast.Tuple)
            and node.args[1].args[0].elts
        ):
            return ast.copy_location(
                self._membership_for_tuple_unit(node.args[0], node.args[1].args[0].elts),
                node,
            )
        if isinstance(node.func, ast.Name) and node.func.id == "len":
            return ast.copy_location(
                ast.Call(func=ast.Name(id="Length", ctx=ast.Load()), args=node.args, keywords=[]),
                node,
            )
        if isinstance(node.func, ast.Name) and node.func.id == "Contains" and len(node.args) == 2:
            seq, elem = node.args
            if isinstance(elem, ast.Constant) and isinstance(elem.value, str):
                return node
            if isinstance(elem, ast.Name):
                return node
            if not (
                isinstance(elem, ast.Call)
                and isinstance(elem.func, ast.Name)
                and elem.func.id == "Unit"
            ):
                elem = ast.Call(
                    func=ast.Name(id="Unit", ctx=ast.Load()),
                    args=[elem],
                    keywords=[],
                )
            return ast.copy_location(
                ast.Call(
                    func=ast.Name(id="Contains", ctx=ast.Load()),
                    args=[seq, elem],
                    keywords=[],
                ),
                node,
            )
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "All_Distinct"
            and any(isinstance(arg, (ast.ListComp, ast.GeneratorExp)) for arg in node.args)
        ):
            # Unsupported comprehensions in formulas: keep surrounding formula parseable.
            return ast.copy_location(ast.Constant(value=True), node)
        return node

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        self.generic_visit(node)
        op_name = "And" if isinstance(node.op, ast.And) else "Or"
        result: ast.expr = node.values[0]
        for value in node.values[1:]:
            result = ast.Call(
                func=ast.Name(id=op_name, ctx=ast.Load()),
                args=[result, value],
                keywords=[],
            )
        return ast.copy_location(result, node)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.op, ast.Not):
            return ast.copy_location(
                ast.Call(
                    func=ast.Name(id="Not", ctx=ast.Load()),
                    args=[node.operand],
                    keywords=[],
                ),
                node,
            )
        return node

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.op, ast.BitAnd):
            return ast.copy_location(
                ast.Call(
                    func=ast.Name(id="And", ctx=ast.Load()),
                    args=[node.left, node.right],
                    keywords=[],
                ),
                node,
            )
        if isinstance(node.op, ast.BitOr):
            return ast.copy_location(
                ast.Call(
                    func=ast.Name(id="Or", ctx=ast.Load()),
                    args=[node.left, node.right],
                    keywords=[],
                ),
                node,
            )
        return node

    def visit_Subscript(self, node: ast.Subscript) -> ast.AST:
        self.generic_visit(node)
        sl = node.slice
        if not isinstance(sl, ast.Slice):
            return node  # plain integer index like seq[k] -- Z3 handles it
        if sl.step is not None:
            return node  # step slices have no clean Extract translation
        seq = node.value
        lower, upper = sl.lower, sl.upper

        def _neg(e: ast.expr | None) -> ast.expr | None:
            if isinstance(e, ast.UnaryOp) and isinstance(e.op, ast.USub):
                return e.operand
            return None

        if lower is None and upper is None:
            return node  # `seq[:]` -- just write `seq`; we don't quietly rewrite

        neg_lower = _neg(lower) if lower is not None else None
        neg_upper = _neg(upper) if upper is not None else None

        length_seq = ast.Call(
            func=ast.Name(id="Length", ctx=ast.Load()),
            args=[seq],
            keywords=[],
        )

        # Five safe rewrites; anything else (mixed negatives, ambiguous bounds)
        # falls through unchanged and the validator will then reject it.
        if neg_lower is not None and upper is None:
            # seq[-K:] -> Extract(seq, Length(seq) - K, K)
            offset: ast.expr = ast.BinOp(left=length_seq, op=ast.Sub(), right=neg_lower)
            length: ast.expr = neg_lower
        elif lower is None and neg_upper is not None:
            # seq[:-K] -> Extract(seq, 0, Length(seq) - K)
            offset = ast.Constant(value=0)
            length = ast.BinOp(left=length_seq, op=ast.Sub(), right=neg_upper)
        elif lower is None and upper is not None and neg_upper is None:
            # seq[:upper] -> Extract(seq, 0, upper)
            offset = ast.Constant(value=0)
            length = upper
        elif lower is not None and neg_lower is None and upper is None:
            # seq[lower:] -> Extract(seq, lower, Length(seq) - lower)
            offset = lower
            length = ast.BinOp(left=length_seq, op=ast.Sub(), right=lower)
        elif lower is not None and neg_lower is None and upper is not None and neg_upper is None:
            # seq[lower:upper] -> Extract(seq, lower, upper - lower)
            offset = lower
            length = ast.BinOp(left=upper, op=ast.Sub(), right=lower)
        else:
            return node

        return ast.copy_location(
            ast.Call(
                func=ast.Name(id="Extract", ctx=ast.Load()),
                args=[seq, offset, length],
                keywords=[],
            ),
            node,
        )

    @staticmethod
    def _tuple_equality_to_and(left: ast.expr, elements: list[ast.expr]) -> ast.expr:
        conjuncts: list[ast.expr] = []
        for index, element in enumerate(elements):
            conjuncts.append(
                ast.Compare(
                    left=ast.Subscript(
                        value=left,
                        slice=ast.Constant(value=index),
                        ctx=ast.Load(),
                    ),
                    ops=[ast.Eq()],
                    comparators=[element],
                )
            )
        result: ast.expr = conjuncts[0]
        for conjunct in conjuncts[1:]:
            result = ast.Call(
                func=ast.Name(id="And", ctx=ast.Load()),
                args=[result, conjunct],
                keywords=[],
            )
        return result

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        if len(node.ops) == 1:
            op = node.ops[0]
            if isinstance(op, ast.Eq) and isinstance(node.comparators[0], ast.Tuple):
                return ast.copy_location(
                    self._tuple_equality_to_and(node.left, node.comparators[0].elts),
                    node,
                )
            if (
                isinstance(node.comparators[0], ast.Constant)
                and isinstance(node.comparators[0].value, str)
            ):
                helper = "Char" if isinstance(node.left, ast.Subscript) else "String"
                str_cmp = ast.copy_location(
                    ast.Call(
                        func=ast.Name(id=helper, ctx=ast.Load()),
                        args=[node.comparators[0]],
                        keywords=[],
                    ),
                    node.comparators[0],
                )
                return ast.copy_location(
                    ast.Compare(left=node.left, ops=node.ops, comparators=[str_cmp]),
                    node,
                )
            if (
                isinstance(op, ast.Eq)
                and isinstance(node.left, ast.Subscript)
                and not isinstance(node.left.value, ast.Subscript)
                and not isinstance(node.left.slice, ast.Constant)
                and isinstance(node.comparators[0], ast.Name)
            ):
                return ast.copy_location(
                    ast.Compare(
                        left=node.left,
                        ops=[ast.Eq()],
                        comparators=[
                            ast.Subscript(
                                value=node.comparators[0],
                                slice=ast.Constant(value=0),
                                ctx=ast.Load(),
                            )
                        ],
                    ),
                    node,
                )
            if (
                isinstance(op, ast.NotEq)
                and isinstance(node.comparators[0], ast.Constant)
                and node.comparators[0].value is None
            ):
                if isinstance(node.left, ast.Subscript):
                    return node
                length_target: ast.expr = node.left
                return ast.copy_location(
                    ast.Compare(
                        left=ast.Call(
                            func=ast.Name(id="Length", ctx=ast.Load()),
                            args=[length_target],
                            keywords=[],
                        ),
                        ops=[ast.Gt()],
                        comparators=[ast.Constant(value=0)],
                    ),
                    node,
                )
            if (
                isinstance(op, ast.Eq)
                and isinstance(node.comparators[0], ast.Constant)
                and node.comparators[0].value is None
            ):
                if isinstance(node.left, ast.Subscript):
                    return node
                return ast.copy_location(
                    ast.Compare(
                        left=ast.Call(
                            func=ast.Name(id="Length", ctx=ast.Load()),
                            args=[node.left],
                            keywords=[],
                        ),
                        ops=[ast.Eq()],
                        comparators=[ast.Constant(value=0)],
                    ),
                    node,
                )
            if not isinstance(op, (ast.In, ast.NotIn)):
                return node
            elem = node.left
            seq = node.comparators[0]
            if isinstance(elem, ast.Tuple) and elem.elts:
                membership = self._membership_for_tuple_unit(seq, elem.elts)
                if isinstance(op, ast.NotIn):
                    return ast.copy_location(
                        ast.Call(
                            func=ast.Name(id="Not", ctx=ast.Load()),
                            args=[membership],
                            keywords=[],
                        ),
                        node,
                    )
                return ast.copy_location(membership, node)
            unit_call = ast.Call(
                func=ast.Name(id="Unit", ctx=ast.Load()),
                args=[elem],
                keywords=[],
            )
            contains_call = ast.Call(
                func=ast.Name(id="Contains", ctx=ast.Load()),
                args=[seq, unit_call],
                keywords=[],
            )
            if isinstance(op, ast.In):
                return ast.copy_location(contains_call, node)
            return ast.copy_location(
                ast.Call(
                    func=ast.Name(id="Not", ctx=ast.Load()),
                    args=[contains_call],
                    keywords=[],
                ),
                node,
            )
        if any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
            return node
        conjuncts: list[ast.expr] = []
        left: ast.expr = node.left
        for op, right in zip(node.ops, node.comparators, strict=True):
            conjuncts.append(ast.Compare(left=left, ops=[op], comparators=[right]))
            left = right
        result = conjuncts[0]
        for conjunct in conjuncts[1:]:
            result = ast.Call(
                func=ast.Name(id="And", ctx=ast.Load()),
                args=[result, conjunct],
                keywords=[],
            )
        return ast.copy_location(result, node)


def extract_quantifier_binders(expr: str) -> set[str]:
    """Return names bound by ForAll([...], ...) / Exists([...], ...) in *expr*."""
    try:
        tree = ast.parse(expr, mode="eval")
    except Exception:
        return set()
    binders: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name):
            continue
        if node.func.id not in {"ForAll", "Exists"}:
            continue
        if not node.args:
            continue
        head = node.args[0]
        if isinstance(head, ast.Name):
            binders.add(head.id)
            continue
        if isinstance(head, (ast.List, ast.Tuple)):
            for element in head.elts:
                if isinstance(element, ast.Name):
                    binders.add(element.id)
    return binders


def ensure_ret_reference(post: str) -> str:
    """Bind a value/property expression that never mentions ``ret`` to ``ret``.

    The single most common extraction failure is a postcondition that states
    the returned *value expression* (``a * b``) or a bare property (``x > 0``)
    without ever naming ``ret``. Such a formula is rejected by validation
    (``must reference ret``) and then sanitized away to ``ret == ret``, which
    both loses information and inflated the degraded-extraction counts.

    Wrapping it as ``ret == (<expr>)`` turns it into a proper postcondition.
    Bare boolean literals are left untouched so they keep being flagged as
    weak rather than being silently promoted into a real constraint.
    """
    stripped = post.strip()
    if not stripped:
        return post
    if stripped in {"True", "False", "(True)", "(False)"}:
        return post
    if _RET_TOKEN.search(stripped):
        return post
    return f"ret == ({stripped})"


def _split_top_level_conjuncts(tree: ast.expr) -> list[ast.expr]:
    """Flatten nested ``And(a, And(b, c))`` / ``a and b`` into ``[a, b, c]``."""
    if isinstance(tree, ast.BoolOp) and isinstance(tree.op, ast.And):
        out: list[ast.expr] = []
        for value in tree.values:
            out.extend(_split_top_level_conjuncts(value))
        return out
    if (
        isinstance(tree, ast.Call)
        and isinstance(tree.func, ast.Name)
        and tree.func.id == "And"
        and tree.args
    ):
        out = []
        for arg in tree.args:
            out.extend(_split_top_level_conjuncts(arg))
        return out
    return [tree]


def salvage_valid_conjuncts(postcondition: str, is_valid: Callable[[str], bool]) -> str:
    """Return the conjunction of the individually-valid conjuncts of *postcondition*.

    When a full postcondition fails validation, it is often a single bad
    conjunct dragging down an otherwise usable formula (e.g. one quantifier
    with a stray comprehension next to three clean comparisons). Rather than
    collapse everything to ``ret == ret``, keep the conjuncts that validate on
    their own. The salvaged formula is logically *weaker* than the original
    intent, which is why callers tag it as a degraded, low-confidence
    extraction. Returns ``""`` when nothing salvageable references ``ret``.
    """
    try:
        tree = ast.parse(postcondition, mode="eval").body
    except Exception:
        return ""
    conjuncts = _split_top_level_conjuncts(tree)
    if len(conjuncts) <= 1:
        return ""
    kept: list[str] = []
    for conjunct in conjuncts:
        try:
            text = ast.unparse(conjunct)
        except Exception:
            continue
        if is_valid(text):
            kept.append(text)
    kept = [text for text in kept if _RET_TOKEN.search(text)] or kept
    if not kept or not any(_RET_TOKEN.search(text) for text in kept):
        return ""
    if len(kept) == 1:
        return kept[0]
    joined = kept[0]
    for text in kept[1:]:
        joined = f"And({joined}, {text})"
    return joined


def normalize_formula(expr: str) -> str:
    try:
        tree = ast.parse(expr, mode="eval")
    except Exception:
        return expr
    transformed = _NormalizeTransformer().visit(tree)
    ast.fix_missing_locations(transformed)
    try:
        return ast.unparse(transformed)
    except Exception:
        return expr


def validate_formula(expr: str, allowed_names: set[str]) -> list[str]:
    errors: list[str] = []
    try:
        tree = ast.parse(expr, mode="eval")
    except Exception as exc:
        return [f"invalid expression syntax: {exc}"]

    if isinstance(tree.body, ast.Tuple):
        return ["expression is a tuple, not a single boolean"]

    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    allowed_nodes = (
        ast.Expression,
        ast.BoolOp,
        ast.BinOp,
        ast.UnaryOp,
        ast.Compare,
        ast.Call,
        ast.Name,
        ast.Constant,
        ast.Load,
        ast.Subscript,
        # ast.Slice deliberately omitted: _NormalizeTransformer.visit_Subscript
        # rewrites the five safe slice forms (a:b, :b, a:, -K:, :-K) into
        # Extract(seq, offset, length) calls. Anything unrewritten (step
        # slices, mixed negatives, seq[:]) reaches validation as a raw Slice
        # node and is rejected here -- previously these silently leaked to
        # p03 and crashed Z3 with 'slice has no attribute as_ast'.
        ast.Tuple,
        ast.List,
        ast.And,
        ast.Or,
        ast.Not,
        ast.USub,
        ast.UAdd,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.FloorDiv,
        ast.Mod,
        ast.Pow,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.RShift,
    )
    for node in ast.walk(tree):
        if not isinstance(node, allowed_nodes):
            errors.append(f"unsupported AST node: {type(node).__name__}")
            break
        if isinstance(node, ast.Call) and not isinstance(node.func, ast.Name):
            errors.append("unsupported function call target")
            break
        if isinstance(node, ast.Name):
            if node.id in {"True", "False"} or node.id in called_names:
                continue
            if node.id not in allowed_names:
                errors.append(f"unknown identifier `{node.id}`")
                break
        if isinstance(node, ast.Attribute):
            errors.append("attribute access must be normalized first")
            break
    return errors
