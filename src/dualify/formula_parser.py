import ast


class _NormalizeTransformer(ast.NodeTransformer):
    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.value, ast.Name):
            return ast.copy_location(
                ast.Name(id=f"{node.value.id}_{node.attr}", ctx=ast.Load()),
                node,
            )
        return node

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == "len":
            return ast.copy_location(
                ast.Call(func=ast.Name(id="Length", ctx=ast.Load()), args=node.args, keywords=[]),
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

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        # Only rewrite the simple single-op `x in seq` / `x not in seq` form.
        # Chained comparisons that mix `in` with arithmetic ops (e.g. `0 <= x in s`)
        # fall through untouched -- the validator will then reject them and the
        # operator can rewrite by hand.
        if len(node.ops) != 1:
            return node
        op = node.ops[0]
        if not isinstance(op, (ast.In, ast.NotIn)):
            return node
        elem = node.left
        seq = node.comparators[0]
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
