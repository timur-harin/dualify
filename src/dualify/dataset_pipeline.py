from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dualify.formula_parser import normalize_formula
from dualify.io_utils import write_json
from dualify.types import BenchmarkCase

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class CanonicalParsedExample:
    source_dataset: str
    source_version: str
    source_file: str
    source_function_id: str
    benchmark_id: str
    qualname: str
    signature: str
    lineno: int
    function_source: str
    arg_types: dict[str, str]
    return_type: str
    raw_contract_blocks: list[dict[str, Any]]
    normalized_domain_constraints: list[str]
    normalized_postcondition: str
    contract_style: str
    contract_confidence: str
    raw_record: dict[str, Any]
    parser_name: str
    parser_version: str
    normalization_notes: list[str]
    parse_errors: list[str]
    informal_spec: str
    extra_context: str
    cleaning_decisions: dict[str, Any] | None = None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _stable_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def _to_type(annotation: ast.expr | None) -> str:
    return ast.unparse(annotation) if annotation is not None else "Any"


def _signature(node: ast.FunctionDef) -> str:
    args = []
    for arg in node.args.args:
        args.append(f"{arg.arg}: {_to_type(arg.annotation)}")
    return f"{node.name}({', '.join(args)}) -> {_to_type(node.returns)}"


def _parse_comments_and_doc(node: ast.FunctionDef, source_lines: list[str]) -> tuple[str, str]:
    idx = node.lineno - 2
    comment_lines: list[str] = []
    while idx >= 0:
        line = source_lines[idx]
        stripped = line.strip()
        if not stripped and not comment_lines:
            idx -= 1
            continue
        if line.lstrip().startswith("#"):
            comment_lines.append(line.lstrip()[1:].strip())
            idx -= 1
            continue
        break
    comment_lines.reverse()

    context: list[str] = []
    desc: list[str] = []
    for line in comment_lines:
        if line.lower().startswith("context:"):
            context.append(line.split(":", 1)[1].strip())
        else:
            desc.append(line)
    doc = (ast.get_docstring(node) or "").strip()
    informal_spec = " ".join(p for p in desc if p).strip() or doc or f"Behavior of {node.name}"
    extra_context = " ".join(p for p in context if p).strip()
    return informal_spec, extra_context


def _extract_lambda_formula(expr: ast.expr) -> str:
    if isinstance(expr, ast.Lambda):
        return ast.unparse(expr.body)
    return ast.unparse(expr)


def _normalize_formula_safe(formula: str, notes: list[str], errors: list[str]) -> str:
    formula = formula.strip()
    if not formula:
        return ""
    # Normalize common result symbol variants first.
    transformed = re.sub(r"\bresult\b", "ret", formula)
    transformed = re.sub(r"\bRET\b", "ret", transformed)
    try:
        return normalize_formula(transformed)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"normalize_failed: {exc}")
        notes.append("kept_raw_formula_due_to_normalize_failure")
        return transformed


def _pep316_contracts(doc: str) -> tuple[list[str], str, list[dict[str, Any]]]:
    if not doc:
        return [], "", []
    pre: list[str] = []
    post: list[str] = []
    blocks: list[dict[str, Any]] = []
    for raw_line in doc.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.lower().startswith("pre:"):
            f = line.split(":", 1)[1].strip()
            pre.append(f)
            blocks.append({"kind": "pre", "style": "pep316", "raw": f})
            continue
        if line.lower().startswith("post"):
            f = line.split(":", 1)[1].strip() if ":" in line else ""
            post.append(f)
            blocks.append({"kind": "post", "style": "pep316", "raw": f})
    return pre, (" and ".join(p for p in post if p)).strip(), blocks


def _decorator_contracts(node: ast.FunctionDef) -> tuple[list[str], str, list[dict[str, Any]], str]:
    pre: list[str] = []
    post: list[str] = []
    blocks: list[dict[str, Any]] = []
    style = "unknown"
    for dec in node.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        dec_name = ast.unparse(dec.func)
        first_arg = dec.args[0] if dec.args else None
        if first_arg is None:
            continue
        formula = _extract_lambda_formula(first_arg)
        lowered = dec_name.lower()
        # icontract corpus typically uses: from icontract import require, ensure
        # so decorators appear as @require / @ensure, not @icontract.require
        base = lowered.split(".")[-1]
        is_pre = (
            "icontract.require" in lowered
            or base in ("require", "pre")
            or lowered.endswith(".require")
            or lowered.endswith(".pre")
        )
        is_post = (
            "icontract.ensure" in lowered
            or base in ("ensure", "post")
            or lowered.endswith(".ensure")
            or lowered.endswith(".post")
        )
        if is_pre:
            pre.append(formula)
            if "icontract" in lowered or base == "require":
                style = "icontract"
            elif "deal" in lowered:
                style = "deal"
            elif style == "unknown":
                style = "icontract"
            blocks.append({"kind": "pre", "style": style, "decorator": dec_name, "raw": formula})
        elif is_post:
            post.append(formula)
            if "icontract" in lowered or base == "ensure":
                style = "icontract"
            elif "deal" in lowered:
                style = "deal"
            elif style == "unknown":
                style = "icontract"
            blocks.append({"kind": "post", "style": style, "decorator": dec_name, "raw": formula})
        elif base in ("inv",) or "invariant" in lowered or lowered.endswith(".inv"):
            style = "deal" if "deal" in lowered else (style if style != "unknown" else "icontract")
            blocks.append({"kind": "invariant", "style": style, "decorator": dec_name, "raw": formula})
    post_formula = " and ".join(p for p in post if p).strip()
    return pre, post_formula, blocks, style


def _iter_module_functions(module: ast.Module) -> list[tuple[ast.FunctionDef, str]]:
    out: list[tuple[ast.FunctionDef, str]] = []
    for node in module.body:
        if isinstance(node, ast.FunctionDef):
            out.append((node, node.name))
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    out.append((item, f"{node.name}.{item.name}"))
    return out


def _collect_function_node(
    dataset_name: str,
    dataset_version: str,
    file_path: Path,
    root: Path,
    node: ast.FunctionDef,
    qualname: str,
    source: str,
    lines: list[str],
    parser_name: str,
    parser_version: str,
) -> CanonicalParsedExample:
    source_file = str(file_path.relative_to(root))
    source_function_id = f"{source_file}:{qualname}:{node.lineno}"
    benchmark_id = f"{dataset_name}::{source_file.replace('/', '::')}::{qualname.replace('.', '::')}"
    arg_types: dict[str, str] = {}
    for arg in node.args.args:
        if arg.arg in ("self", "cls") and arg.annotation is None:
            continue
        arg_types[arg.arg] = _to_type(arg.annotation)
    ret_type = _to_type(node.returns)
    function_source = ast.get_source_segment(source, node) or ""
    informal_spec, extra_context = _parse_comments_and_doc(node, lines)

    notes: list[str] = []
    errors: list[str] = []
    pre_d, post_d, blocks_d, style_d = _decorator_contracts(node)
    pre_p, post_p, blocks_p = _pep316_contracts(ast.get_docstring(node) or "")

    pre_all = pre_d + pre_p
    post_raw = " and ".join(filter(None, [post_d, post_p])).strip()
    contract_style = style_d if style_d != "unknown" else ("pep316" if blocks_p else "unknown")
    raw_blocks = blocks_d + blocks_p

    if not raw_blocks:
        notes.append("no_explicit_contract_block_found")
    norm_pre = [_normalize_formula_safe(item, notes, errors) for item in pre_all if item.strip()]
    norm_post = _normalize_formula_safe(post_raw, notes, errors) if post_raw else ""

    confidence = "high"
    if errors:
        confidence = "medium"
    if not norm_post and not norm_pre:
        confidence = "low"
    elif not norm_post:
        confidence = "medium"

    raw_record = {
        "dataset_root": str(root),
        "source_file_abs": str(file_path),
        "function_ast_type": type(node).__name__,
        "docstring": ast.get_docstring(node) or "",
        "decorators": [ast.unparse(d) for d in node.decorator_list],
    }
    return CanonicalParsedExample(
        source_dataset=dataset_name,
        source_version=dataset_version,
        source_file=source_file,
        source_function_id=source_function_id,
        benchmark_id=benchmark_id,
        qualname=qualname,
        signature=_signature(node),
        lineno=node.lineno,
        function_source=function_source,
        arg_types=arg_types,
        return_type=ret_type,
        raw_contract_blocks=raw_blocks,
        normalized_domain_constraints=norm_pre,
        normalized_postcondition=norm_post,
        contract_style=contract_style,
        contract_confidence=confidence,
        raw_record=raw_record,
        parser_name=parser_name,
        parser_version=parser_version,
        normalization_notes=notes,
        parse_errors=errors,
        informal_spec=informal_spec,
        extra_context=extra_context,
    )


def _collect_python_functions(dataset_name: str, dataset_version: str, root: Path) -> list[CanonicalParsedExample]:
    parser_name = "dualify.dataset_pipeline"
    parser_version = "1.0"
    records: list[CanonicalParsedExample] = []
    for file_path in sorted(root.rglob("*.py")):
        source = file_path.read_text(encoding="utf-8")
        lines = source.splitlines()
        try:
            module = ast.parse(source)
        except SyntaxError:
            continue

        for node, qualname in _iter_module_functions(module):
            records.append(
                _collect_function_node(
                    dataset_name,
                    dataset_version,
                    file_path,
                    root,
                    node,
                    qualname,
                    source,
                    lines,
                    parser_name,
                    parser_version,
                )
            )
    return records


def _has_type_info_minimum_record(record: CanonicalParsedExample) -> bool:
    """Return annotated and every collected parameter typed (self/cls omitted when unannotated)."""
    if record.return_type.strip() == "Any":
        return False
    if not record.arg_types:
        return True
    return all(v.strip() != "Any" for v in record.arg_types.values())


def _clean_record(record: CanonicalParsedExample) -> tuple[bool, dict[str, Any]]:
    semantic_key = _stable_hash(record.function_source, record.normalized_postcondition)
    post_norm = record.normalized_postcondition.strip()
    try:
        post_norm_cmp = normalize_formula(post_norm).replace(" ", "") if post_norm else ""
    except Exception:  # noqa: BLE001
        post_norm_cmp = post_norm.replace(" ", "")
    decisions: dict[str, Any] = {
        "is_python_function": bool(record.function_source.strip()),
        "has_explicit_contract": bool(record.raw_contract_blocks),
        "has_type_info_minimum": _has_type_info_minimum_record(record),
        "has_normalized_postcondition": bool(post_norm),
        "contract_parseable_for_smt": bool(post_norm),
        "deduplicated_by_semantic_key": semantic_key,
        "non_trivial_contract": post_norm_cmp not in {"", "ret==ret", "true", "(true)"},
    }
    accept = (
        decisions["is_python_function"]
        and decisions["has_explicit_contract"]
        and decisions["has_type_info_minimum"]
        and decisions["has_normalized_postcondition"]
        and decisions["non_trivial_contract"]
    )
    return accept, decisions


def _case_from_record(record: CanonicalParsedExample) -> BenchmarkCase:
    return BenchmarkCase(
        benchmark_id=record.benchmark_id,
        file=f"{record.source_dataset}/{record.source_file}",
        qualname=record.qualname,
        lineno=record.lineno,
        signature=record.signature,
        arg_types=record.arg_types,
        return_type=record.return_type,
        informal_spec=record.informal_spec,
        extra_context=record.extra_context,
        function_source=record.function_source,
    )


def _evaluation_row(record: CanonicalParsedExample) -> dict[str, Any]:
    return {
        "benchmark_id": record.benchmark_id,
        "source_dataset": record.source_dataset,
        "source_file": record.source_file,
        "qualname": record.qualname,
        "gold_spec_to_logic": {
            "domain_constraints": record.normalized_domain_constraints,
            "postcondition": record.normalized_postcondition,
            "confidence": record.contract_confidence,
            "notes": "; ".join(record.normalization_notes),
        },
        "raw_contract_blocks": record.raw_contract_blocks,
        "contract_style": record.contract_style,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_dataset_pipeline(
    *,
    python_by_contract_path: str,
    crosshair_examples_path: str,
    output_dir: str = "results/dataset_pipeline",
    apply_cleaning: bool = False,
) -> dict[str, Any]:
    run_stamp = datetime.now(UTC).strftime("%Y_%m_%d_%H_%M_%S")
    out_root = (ROOT / output_dir / run_stamp).resolve()
    raw_dir = out_root / "raw"
    clean_dir = out_root / "clean"
    reject_dir = out_root / "rejects"

    pbc_root = Path(python_by_contract_path).expanduser().resolve()
    crosshair_root = Path(crosshair_examples_path).expanduser().resolve()
    if not pbc_root.exists():
        raise FileNotFoundError(f"python_by_contract_path not found: {pbc_root}")
    if not crosshair_root.exists():
        raise FileNotFoundError(f"crosshair_examples_path not found: {crosshair_root}")

    pbc_records = _collect_python_functions("python_by_contract", "unknown", pbc_root)
    crosshair_records = _collect_python_functions("crosshair_examples", "unknown", crosshair_root)
    all_records = pbc_records + crosshair_records

    # Assign cleaning decisions preview for all records (confirmation checkpoint support).
    decision_rows: list[dict[str, Any]] = []
    accepted: list[CanonicalParsedExample] = []
    rejected: list[dict[str, Any]] = []
    semantic_seen: set[str] = set()
    for record in all_records:
        accept, decisions = _clean_record(record)
        semantic_key = decisions["deduplicated_by_semantic_key"]
        if semantic_key in semantic_seen:
            decisions["duplicate_reject"] = True
            accept = False
        else:
            decisions["duplicate_reject"] = False
            if accept:
                semantic_seen.add(semantic_key)
        record.cleaning_decisions = decisions
        decision_rows.append(
            {
                "benchmark_id": record.benchmark_id,
                "source_dataset": record.source_dataset,
                "cleaning_decisions": decisions,
                "accept_candidate": accept,
            }
        )
        if accept:
            accepted.append(record)
        else:
            rejected.append(
                {
                    "benchmark_id": record.benchmark_id,
                    "source_dataset": record.source_dataset,
                    "reject_reasons": [
                        key
                        for key, value in decisions.items()
                        if key != "deduplicated_by_semantic_key" and value is False
                    ]
                    + (["duplicate_reject"] if decisions.get("duplicate_reject") else []),
                    "cleaning_decisions": decisions,
                }
            )

    raw_payload = [asdict(item) for item in all_records]
    write_json(raw_dir / "canonical_records.json", raw_payload)
    _write_jsonl(raw_dir / "canonical_records.jsonl", raw_payload)
    write_json(raw_dir / "cleaning_decisions_preview.json", decision_rows)

    # Always prepare compatibility/evaluation exports from raw and (optionally) clean.
    raw_cases = [asdict(_case_from_record(item)) for item in all_records]
    raw_eval = [_evaluation_row(item) for item in all_records]
    write_json(raw_dir / "dualify_cases.json", raw_cases)
    _write_jsonl(raw_dir / "evaluation_index.jsonl", raw_eval)

    manifest = {
        "created_at_utc": _utc_now(),
        "pipeline": "dualify.dataset_pipeline",
        "pipeline_version": "1.0",
        "sources": {
            "python_by_contract_path": str(pbc_root),
            "crosshair_examples_path": str(crosshair_root),
        },
        "counts": {
            "raw_total": len(all_records),
            "raw_python_by_contract": len(pbc_records),
            "raw_crosshair_examples": len(crosshair_records),
            "accepted_preview": len(accepted),
            "rejected_preview": len(rejected),
        },
        "apply_cleaning": apply_cleaning,
    }
    write_json(out_root / "dataset_manifest.json", manifest)

    if not apply_cleaning:
        preview_report = {
            "status": "awaiting_cleaning_confirmation",
            "run_dir": str(out_root),
            "message": "Raw snapshot and objective cleaning preview are ready. Re-run with --apply-cleaning after confirmation.",
            "summary": manifest["counts"],
        }
        write_json(out_root / "checkpoint_preview.json", preview_report)
        return preview_report

    clean_payload = [asdict(item) for item in accepted]
    reject_payload = rejected
    write_json(clean_dir / "canonical_records.json", clean_payload)
    _write_jsonl(clean_dir / "canonical_records.jsonl", clean_payload)
    write_json(reject_dir / "rejected_records.json", reject_payload)
    _write_jsonl(reject_dir / "rejected_records.jsonl", reject_payload)

    clean_cases = [asdict(_case_from_record(item)) for item in accepted]
    clean_eval = [_evaluation_row(item) for item in accepted]
    write_json(clean_dir / "dualify_cases.json", clean_cases)
    _write_jsonl(clean_dir / "evaluation_index.jsonl", clean_eval)

    lineage = []
    accepted_ids = {item.benchmark_id for item in accepted}
    for item in all_records:
        if item.benchmark_id in accepted_ids:
            lineage.append({"raw_id": item.benchmark_id, "status": "kept", "clean_id": item.benchmark_id})
        else:
            reject_reasons = next(
                (row["reject_reasons"] for row in rejected if row["benchmark_id"] == item.benchmark_id),
                [],
            )
            lineage.append({"raw_id": item.benchmark_id, "status": "rejected", "reject_reasons": reject_reasons})
    write_json(out_root / "lineage.json", lineage)

    reject_reason_hist: dict[str, int] = {}
    for row in rejected:
        for reason in row["reject_reasons"]:
            reject_reason_hist[reason] = reject_reason_hist.get(reason, 0) + 1
    cleaning_report = {
        "created_at_utc": _utc_now(),
        "total_raw": len(all_records),
        "total_clean": len(accepted),
        "total_rejected": len(rejected),
        "reject_reason_histogram": reject_reason_hist,
    }
    write_json(out_root / "cleaning_report.json", cleaning_report)

    final_report = {
        "status": "cleaning_completed",
        "run_dir": str(out_root),
        "summary": {
            "raw_total": len(all_records),
            "clean_total": len(accepted),
            "rejected_total": len(rejected),
        },
    }
    write_json(out_root / "final_report.json", final_report)
    return final_report


def _main() -> None:
    parser = argparse.ArgumentParser(description="Parse, normalize, and clean Python contract datasets")
    parser.add_argument("--python-by-contract-path", required=True)
    parser.add_argument("--crosshair-examples-path", required=True)
    parser.add_argument("--output-dir", default="results/dataset_pipeline")
    parser.add_argument("--apply-cleaning", action="store_true")
    args = parser.parse_args()

    report = run_dataset_pipeline(
        python_by_contract_path=args.python_by_contract_path,
        crosshair_examples_path=args.crosshair_examples_path,
        output_dir=args.output_dir,
        apply_cleaning=args.apply_cleaning,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    _main()
