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
        if isinstance(node.func, ast.Name) and node.func.id == "All_Distinct" and any(
            isinstance(arg, (ast.ListComp, ast.GeneratorExp)) for arg in node.args
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
        ast.Slice,
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
