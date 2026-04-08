import ast
from pathlib import Path

from dualify.types import BenchmarkCase


def _annotation_to_type(annotation: ast.expr | None, file_path: Path, arg_name: str) -> str:
    if annotation is None:
        raise ValueError(f"Missing type annotation for '{arg_name}' in {file_path}")
    return ast.unparse(annotation)


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


def _iter_python_files(base_dir: Path, recursive: bool) -> list[Path]:
    pattern = "**/*.py" if recursive else "*.py"
    return sorted(path for path in base_dir.glob(pattern) if path.is_file())


def _discover_cases(
    base_dir: Path,
    root_dir: Path,
    *,
    recursive: bool,
    skip_unsupported: bool,
    benchmark_id_prefix_with_path: bool,
) -> list[BenchmarkCase]:
    cases: list[BenchmarkCase] = []
    for file_path in _iter_python_files(base_dir, recursive=recursive):
        source = file_path.read_text(encoding="utf-8")
        source_lines = source.splitlines()
        try:
            module = ast.parse(source)
        except SyntaxError:
            if skip_unsupported:
                continue
            raise

        relative_file = str(file_path.relative_to(root_dir))

        def add_case(
            node: ast.FunctionDef,
            *,
            qualname: str,
            local_file_path: Path,
            local_source_lines: list[str],
            local_source: str,
            local_relative_file: str,
        ) -> None:
            arg_types: dict[str, str] = {}
            try:
                for arg in node.args.args:
                    if arg.arg in {"self", "cls"} and arg.annotation is None:
                        continue
                    arg_types[arg.arg] = _annotation_to_type(
                        arg.annotation,
                        local_file_path,
                        arg.arg,
                    )
                return_type = _annotation_to_type(node.returns, local_file_path, "return")
            except ValueError:
                if skip_unsupported:
                    return
                raise

            informal_spec, extra_context = _extract_spec_parts(node, local_source_lines)
            function_source = ast.get_source_segment(local_source, node) or local_source
            benchmark_id = qualname
            if benchmark_id_prefix_with_path:
                benchmark_id = (
                    f"{local_relative_file.replace('/', '::')}::{qualname.replace('.', '::')}"
                )

            cases.append(
                BenchmarkCase(
                    benchmark_id=benchmark_id,
                    file=local_relative_file,
                    qualname=qualname,
                    lineno=node.lineno,
                    signature=_format_signature(node),
                    arg_types=arg_types,
                    return_type=return_type,
                    informal_spec=informal_spec,
                    extra_context=extra_context,
                    function_source=function_source,
                )
            )

        for node in module.body:
            if isinstance(node, ast.FunctionDef):
                add_case(
                    node,
                    qualname=node.name,
                    local_file_path=file_path,
                    local_source_lines=source_lines,
                    local_source=source,
                    local_relative_file=relative_file,
                )
                continue
            if isinstance(node, ast.ClassDef):
                for class_item in node.body:
                    if isinstance(class_item, ast.FunctionDef):
                        add_case(
                            class_item,
                            qualname=f"{node.name}.{class_item.name}",
                            local_file_path=file_path,
                            local_source_lines=source_lines,
                            local_source=source,
                            local_relative_file=relative_file,
                        )
    return sorted(cases, key=lambda item: item.benchmark_id)


def discover_python_cases(benchmark_dir: Path, root_dir: Path) -> list[BenchmarkCase]:
    return _discover_cases(
        benchmark_dir,
        root_dir,
        recursive=False,
        skip_unsupported=False,
        benchmark_id_prefix_with_path=False,
    )


def discover_repo_cases(repo_dir: Path) -> list[BenchmarkCase]:
    return _discover_cases(
        repo_dir,
        repo_dir,
        recursive=True,
        skip_unsupported=True,
        benchmark_id_prefix_with_path=True,
    )

