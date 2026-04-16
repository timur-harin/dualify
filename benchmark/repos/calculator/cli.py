"""Tiny CLI for the mock calculator package."""

import argparse

from .history import History
from .parser import evaluate_expression


def main() -> None:
    """Parse one expression from CLI, evaluate, print result.

    Postconditions:
    - Prints computed numeric result to stdout.
    """
    parser = argparse.ArgumentParser(description="Evaluate arithmetic expressions.")
    parser.add_argument("expression", help='Expression like "2 + 3 * 4"')
    args = parser.parse_args()

    history = History()
    result = evaluate_expression(args.expression)
    history.push(args.expression, result)
    print(result)


if __name__ == "__main__":
    main()
