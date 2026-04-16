"""Safe arithmetic expression evaluator."""

import ast
import operator

from .errors import CalculationError, ExpressionSyntaxError

Number = int | float

_BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def evaluate_expression(expression: str) -> float:
    """Evaluate arithmetic expression with a restricted AST.

    Preconditions:
    - `expression` is a valid arithmetic expression using supported operators.

    Postconditions:
    - Returns numeric value as `float`.

    Raises:
    - ExpressionSyntaxError: when expression cannot be parsed.
    - CalculationError: when expression uses unsupported syntax or invalid operations.
    """
    try:
        node = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ExpressionSyntaxError(f"Invalid expression syntax: {expression}") from exc
    return float(_eval_node(node.body))


def _eval_node(node: ast.AST) -> Number:
    """Evaluate one AST node from the restricted grammar.

    Preconditions:
    - `node` comes from `ast.parse(..., mode="eval")`.

    Postconditions:
    - Returns `int` or `float` for supported nodes.

    Raises:
    - CalculationError: for unsupported nodes/operators or division/modulo by zero.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value

    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _BINARY_OPS:
            raise CalculationError(f"Unsupported binary operator: {op_type.__name__}")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if op_type in (ast.Div, ast.Mod) and right == 0:
            raise CalculationError("Division or modulo by zero in expression.")
        return _BINARY_OPS[op_type](left, right)

    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _UNARY_OPS:
            raise CalculationError(f"Unsupported unary operator: {op_type.__name__}")
        return _UNARY_OPS[op_type](_eval_node(node.operand))

    raise CalculationError(f"Unsupported syntax node: {type(node).__name__}")
