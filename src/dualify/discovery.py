import ast
from pathlib import Path

from dualify.types import BenchmarkCase


def _annotation_to_type(annotation: ast.expr | None, file_path: Path, arg_name: str) -> str:
    if annotation is None:
        raise ValueError(f"Missing type annotation for '{arg_name}' in {file_path}")
    text = ast.unparse(annotation)
    if text not in {"int", "bool"}:
        raise ValueError(
            f"Unsupported type '{text}' for '{arg_name}' in {file_path}. "
            "Only int and bool are supported."
        )
    return text


def _extract_comment_block(lines: list[str], func_lineno: int) -> list[str]:
    idx = func_lineno - 2
    block: list[str] = []
    while idx >= 0:
        line = lines[idx]
        stripped = line.strip()
        if stripped == "":
            if block:
                break
            idx -= 1
            continue
        if line.lstrip().startswith("#"):
            block.append(line.lstrip()[1:].strip())
            idx -= 1
            continue
        break
    block.reverse()
    return block


def _extract_spec_parts(node: ast.FunctionDef, source_lines: list[str]) -> tuple[str, str]:
    comments = _extract_comment_block(source_lines, node.lineno)
    description_lines: list[str] = []
    context_lines: list[str] = []
    for line in comments:
        if line.lower().startswith("context:"):
            context_lines.append(line.split(":", 1)[1].strip())
        else:
            description_lines.append(line)

    informal_spec = " ".join(line for line in description_lines if line).strip()
    extra_context = " ".join(line for line in context_lines if line).strip()

    if not informal_spec:
        doc = ast.get_docstring(node)
        informal_spec = (doc or "").strip()

    if not informal_spec:
        informal_spec = f"Describe behavior of function '{node.name}'."

    return informal_spec, extra_context


def _format_signature(node: ast.FunctionDef) -> str:
    parts: list[str] = []
    for arg in node.args.args:
        ann = ast.unparse(arg.annotation) if arg.annotation else "Any"
        parts.append(f"{arg.arg}: {ann}")
    ret = ast.unparse(node.returns) if node.returns else "Any"
    return f"{node.name}({', '.join(parts)}) -> {ret}"


def discover_python_cases(benchmark_dir: Path, root_dir: Path) -> list[BenchmarkCase]:
    cases: list[BenchmarkCase] = []
    for file_path in sorted(benchmark_dir.glob("*.py")):
        source = file_path.read_text(encoding="utf-8")
        source_lines = source.splitlines()
        module = ast.parse(source)

        for node in module.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            arg_types: dict[str, str] = {}
            for arg in node.args.args:
                arg_types[arg.arg] = _annotation_to_type(arg.annotation, file_path, arg.arg)

            return_type = _annotation_to_type(node.returns, file_path, "return")
            informal_spec, extra_context = _extract_spec_parts(node, source_lines)
            function_source = ast.get_source_segment(source, node) or source

            cases.append(
                BenchmarkCase(
                    benchmark_id=node.name,
                    file=str(file_path.relative_to(root_dir)),
                    signature=_format_signature(node),
                    arg_types=arg_types,
                    return_type=return_type,
                    informal_spec=informal_spec,
                    extra_context=extra_context,
                    function_source=function_source,
                )
            )

    return sorted(cases, key=lambda item: item.benchmark_id)

