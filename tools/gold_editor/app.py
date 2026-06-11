"""Streamlit editor for hand-curating the Dualify gold benchmark.

For each candidate function from the dataset, the operator writes:
- a one-sentence profile (in-scope / out-of-scope / observable boundary),
- a reference precondition (`reference_pre`, one conjunct per line),
- a reference postcondition (`reference_post`, single Boolean expression in `ret`),
- an `in_fragment` flag plus free-form notes.

Confirmed cases land under ``benchmark/lifted/<benchmark_id>.yaml``. The two
formula fields are validated live against the Dualify fragment via
``dualify.formula_parser.normalize_formula`` + ``validate_formula`` and the
Confirm button is disabled while there are validation errors (unless the user
explicitly marks the case as out of fragment, in which case validation is
skipped but the formulas are not stored as `reference_normalized`).
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import streamlit as st
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_DIR = Path(__file__).resolve().parent
for _p in (REPO_ROOT / "src", TOOL_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from dataset_lift import lift_to_fragment, strip_formal_lines, strip_metadata_notes  # noqa: E402

from dualify.formula_parser import normalize_formula, validate_formula  # noqa: E402

DEFAULT_DATASET = (
    REPO_ROOT
    / "benchmark"
    / "dataset"
    / "runs"
    / "2026_05_05_08_59_47"
    / "clean"
    / "canonical_records.json"
)
LIFTED_DIR = REPO_ROOT / "benchmark" / "lifted"

# Spec values we treat as "not a real spec" regardless of length.
JUNK_SPEC_LITERALS = {
    "",
    "fmt: on",
    "fmt: off",
    "pass",
    "...",
    "TODO",
    "FIXME",
}
# Stripped informal_spec must be at least this many characters to count.
MIN_SPEC_CHARS = 10


@dataclass
class Candidate:
    benchmark_id: str
    qualname: str
    file: str
    signature: str
    arg_types: dict[str, str]
    return_type: str
    informal_spec: str
    function_source: str
    extra_context: str
    raw_contract_blocks: list[dict[str, str]]
    normalized_domain_constraints: list[str]
    normalized_postcondition: str

    @property
    def allowed_names(self) -> set[str]:
        # Mirror p01_spec_to_logic._extract_self_symbols but generalize to any
        # signature arg: any `<arg>.<attr>` reference in the informal spec /
        # extra context / function source / contract blocks admits
        # `<arg>_<attr>` as a known identifier. This matches what
        # formula_parser._NormalizeTransformer produces (it rewrites
        # `cart.items` -> `cart_items`) so the operator can write attribute
        # access naturally; the validator treats the normalized name as an
        # opaque Z3 variable.
        text_sources = [
            self.informal_spec,
            self.extra_context,
            self.function_source,
            self.normalized_postcondition,
            *self.normalized_domain_constraints,
            *(b.get("raw", "") for b in self.raw_contract_blocks),
        ]
        joined = "\n".join(t or "" for t in text_sources)
        bases = set(self.arg_types.keys()) | {"self"}
        bases_re = "|".join(re.escape(n) for n in bases) if bases else "(?!)"
        attr_pairs = re.findall(rf"\b({bases_re})\.([A-Za-z_][A-Za-z0-9_]*)\b", joined)
        derived = {f"{base}_{attr}" for base, attr in attr_pairs}
        return set(self.arg_types.keys()) | {"ret"} | derived

    @property
    def safe_slug(self) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", self.benchmark_id).strip("_")

    @property
    def has_meaningful_informal_prose(self) -> bool:
        """True iff the informal_spec carries real prose beyond formulas and meta-notes.

        Strips PEP316 / icontract `pre:`/`post:`/`raises:` directives and
        metadata markers (`NOTE:` / `TODO:` / `FIXME:` / ...) -- both stand in
        for, but are not, a description of the function -- and applies the
        gross length filter to whatever's left. Specs like
        `post: __return__ != "moo"` or
        `NOTE: This is an example of contracts on recursive functions.` fail
        this and are useless for the [informal spec -> formal spec] half of
        the benchmark.
        """
        clean, _ = strip_formal_lines(self.informal_spec)
        clean, _ = strip_metadata_notes(clean)
        return has_meaningful_informal_spec(clean)

    @property
    def is_bug_example(self) -> bool:
        # Crosshair organizes deliberately-broken contracts under bugs_detected/,
        # often with verdict-leaking comments like "# False (on an empty list)".
        # Good for SMT-side benchmarking, bad for [informal spec -> formal spec]
        # because the contract itself is intentionally wrong (and the comment,
        # when present, already reveals the answer). Detected via either the
        # path marker in benchmark_id or `# True`/`# False` lines in the spec.
        if "bugs_detected" in (self.benchmark_id or "") or "bugs_detected" in (self.file or ""):
            return True
        return bool(re.search(r"(?im)^\s*#\s*(true|false)\b", self.informal_spec or ""))


def has_meaningful_informal_spec(spec: str) -> bool:
    stripped = (spec or "").strip()
    if stripped in JUNK_SPEC_LITERALS:
        return False
    return len(stripped) >= MIN_SPEC_CHARS


@st.cache_data(show_spinner=False)
def load_candidates(dataset_path: str) -> list[Candidate]:
    raw = json.loads(Path(dataset_path).read_text())
    out: list[Candidate] = []
    for rec in raw:
        if not has_meaningful_informal_spec(rec.get("informal_spec", "")):
            continue
        out.append(
            Candidate(
                benchmark_id=rec["benchmark_id"],
                qualname=rec["qualname"],
                file=rec.get("file", ""),
                signature=rec["signature"],
                arg_types=rec.get("arg_types") or {},
                return_type=rec.get("return_type", ""),
                informal_spec=rec.get("informal_spec", ""),
                function_source=rec.get("function_source", ""),
                extra_context=rec.get("extra_context", "") or "",
                raw_contract_blocks=rec.get("raw_contract_blocks") or [],
                normalized_domain_constraints=rec.get("normalized_domain_constraints") or [],
                normalized_postcondition=rec.get("normalized_postcondition", "") or "",
            )
        )
    out.sort(key=lambda c: c.benchmark_id)
    return out


def prepopulate(candidate: Candidate) -> dict[str, Any]:
    """Build the unconfirmed-card defaults: stripped spec + lifted contract."""
    clean_spec, stripped_directives = strip_formal_lines(candidate.informal_spec)
    clean_spec, stripped_notes = strip_metadata_notes(clean_spec)
    pre_lines = [lift_to_fragment(c) for c in candidate.normalized_domain_constraints]
    post = lift_to_fragment(candidate.normalized_postcondition or "")
    return {
        "informal_spec_clean": clean_spec,
        "stripped_directives": stripped_directives,
        "stripped_metadata_notes": stripped_notes,
        "reference_pre": pre_lines,
        "reference_post": post,
    }


def yaml_path_for(candidate: Candidate) -> Path:
    return LIFTED_DIR / f"{candidate.safe_slug}.yaml"


def load_lifted(candidate: Candidate) -> dict[str, Any] | None:
    """Load the YAML at benchmark/lifted/<slug>.yaml regardless of status."""
    path = yaml_path_for(candidate)
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text()) or {}


def is_confirmed(payload: dict[str, Any] | None) -> bool:
    """A YAML counts as confirmed iff its `status` field is exactly `confirmed`.

    Unknown / missing status defaults to `unreviewed`, matching the value the
    bulk-seed script writes for AI-generated drafts.
    """
    if not payload:
        return False
    return payload.get("status") == "confirmed"


def needs_attention(payload: dict[str, Any] | None) -> bool:
    """Read the `needs_attention` flag from a YAML payload.

    Missing/null is treated as False. The operator sets the flag via the
    editor checkbox to mark a card for a second look.
    """
    if not payload:
        return False
    return bool(payload.get("needs_attention", False))


def parse_pre_lines(raw: str) -> list[str]:
    """Split a multi-line textarea into one conjunct per non-empty line."""
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _extract_quantifier_binders(expr: str) -> set[str]:
    """Harvest bound names introduced by ForAll([k1, k2, ...], body) / Exists(...).

    The gold editor admits Z3-native quantifier syntax over collections (per
    M2 scope decision). The shared formula_parser doesn't yet understand it,
    so we union the binder names into allowed_names locally before calling
    validate_formula. Nested quantifiers each contribute their own binders.

    Only flat `[name, name, ...]` first-args are recognized. Anything else
    (a non-list first arg, or non-name items in the list) is ignored here and
    will be surfaced by validate_formula's normal "unknown identifier" path.
    """
    import ast

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
        if not isinstance(head, ast.List):
            continue
        for el in head.elts:
            if isinstance(el, ast.Name):
                binders.add(el.id)
    return binders


def validate_many(lines: list[str], allowed_names: set[str]) -> list[tuple[int, str, list[str]]]:
    """Return list of (index, normalized_line, errors) for each non-empty line."""
    report: list[tuple[int, str, list[str]]] = []
    for idx, line in enumerate(lines):
        normalized = normalize_formula(line)
        extended = allowed_names | _extract_quantifier_binders(normalized)
        errors = validate_formula(normalized, extended)
        report.append((idx, normalized, errors))
    return report


def _render_validation_block(
    report: list[tuple[int, str, list[str]]],
    raw_lines: list[str],
    kind: str,
) -> None:
    """Render per-line validation feedback directly under the input it pertains to."""
    if not report:
        if kind == "pre":
            st.caption("Validation: reference_pre is empty (treated as `True`).")
        else:
            st.warning("Validation: reference_post is empty.")
        return
    for i, normalized, errors in report:
        raw = raw_lines[i]
        label = f"{kind}[{i}]" if kind == "pre" else "post"
        rewrote = normalized.strip() != raw.strip()
        if errors:
            err_text = ", ".join(errors)
            if rewrote:
                st.error(
                    f"{label} `{raw}` → normalized to `{normalized}` → {err_text}",
                    icon="⚠️",
                )
            else:
                st.error(f"{label} `{raw}` → {err_text}", icon="⚠️")
        else:
            if rewrote:
                st.success(f"{label} OK · `{raw}` → `{normalized}`", icon="✅")
            else:
                st.success(f"{label} OK · `{normalized}`", icon="✅")


def save_yaml(candidate: Candidate, payload: dict[str, Any]) -> Path:
    LIFTED_DIR.mkdir(parents=True, exist_ok=True)
    path = yaml_path_for(candidate)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))
    return path


def render_candidate_picker(candidates: list[Candidate]) -> int:
    if "cursor" not in st.session_state:
        st.session_state.cursor = 0

    total = len(candidates)
    lifted_payloads = [load_lifted(c) for c in candidates]
    confirmed_flags = [is_confirmed(p) for p in lifted_payloads]
    draft_flags = [(p is not None) and (not is_confirmed(p)) for p in lifted_payloads]
    attention_flags = [needs_attention(p) for p in lifted_payloads]
    confirmed_count = sum(confirmed_flags)
    draft_count = sum(draft_flags)
    attention_count = sum(attention_flags)
    bug_count = sum(1 for c in candidates if c.is_bug_example)
    no_prose_count = sum(1 for c in candidates if not c.has_meaningful_informal_prose)

    st.sidebar.markdown(
        f"**Progress:** {confirmed_count}/{total} confirmed · {draft_count} drafted · "
        f"{attention_count} needs-attention"
    )
    show_only = st.sidebar.radio(
        "Show",
        ["All", "Unconfirmed", "Confirmed", "Drafted (unreviewed)"],
        index=0,
        key="filter_mode",
    )
    only_attention = st.sidebar.checkbox(
        f"Only show needs-attention ({attention_count})",
        value=False,
        key="filter_needs_attention",
        help=(
            "Show only YAMLs whose `needs_attention` field is True -- e.g. the "
            "contract is hard to capture or the formulas didn't validate. "
            "Combines with the Show filter above (intersection)."
        ),
    )
    hide_bug_examples = st.sidebar.checkbox(
        f"Hide crosshair bug-detection examples ({bug_count})",
        value=True,
        key="hide_bugs",
        help=(
            "Records under bugs_detected/ or with `# True`/`# False` verdict-"
            "leak comments are good SMT benchmarks but not [informal spec -> "
            "formal spec] benchmarks."
        ),
    )
    hide_no_prose = st.sidebar.checkbox(
        f"Hide records with no prose after stripping formulas / meta-notes ({no_prose_count})",
        value=True,
        key="hide_no_prose",
        help=(
            "After removing PEP316 / icontract `pre:` / `post:` / `raises:` "
            "directives AND metadata markers like `NOTE:` / `TODO:` / `FIXME:`, "
            "what's left must still be a real natural-language description "
            "(≥ 10 non-junk chars). Cases that fail this are useful for the "
            "SMT half of the benchmark but not for [informal spec → formal spec]."
        ),
    )
    qsearch = st.sidebar.text_input(
        "Filter by benchmark_id / qualname substring", value="", key="filter_q"
    )

    def visible(i: int) -> bool:
        if show_only == "Confirmed" and not confirmed_flags[i]:
            return False
        if show_only == "Unconfirmed" and confirmed_flags[i]:
            return False
        if show_only == "Drafted (unreviewed)" and not draft_flags[i]:
            return False
        if only_attention and not attention_flags[i]:
            return False
        if hide_bug_examples and candidates[i].is_bug_example:
            return False
        if hide_no_prose and not candidates[i].has_meaningful_informal_prose:
            return False
        if qsearch:
            hay = (candidates[i].benchmark_id + " " + candidates[i].qualname).lower()
            if qsearch.lower() not in hay:
                return False
        return True

    visible_indices = [i for i in range(total) if visible(i)]
    if not visible_indices:
        st.sidebar.warning("No candidates match this filter.")
        return st.session_state.cursor

    if st.session_state.cursor not in visible_indices:
        # The current card got filtered out (typically: just confirmed while
        # in "Unconfirmed" mode, or just unconfirmed while in "Confirmed"
        # mode). Advance to the next visible card after the old cursor; wrap
        # to the first if we ran off the end. Avoid snapping back to index 0
        # -- that would lose the operator's place.
        old = st.session_state.cursor
        nxt = next((i for i in visible_indices if i > old), visible_indices[0])
        st.session_state.cursor = nxt

    col_prev, col_next = st.sidebar.columns(2)
    if col_prev.button("◀ Prev", use_container_width=True):
        pos = visible_indices.index(st.session_state.cursor)
        st.session_state.cursor = visible_indices[(pos - 1) % len(visible_indices)]
        st.rerun()
    if col_next.button("Next ▶", use_container_width=True):
        pos = visible_indices.index(st.session_state.cursor)
        st.session_state.cursor = visible_indices[(pos + 1) % len(visible_indices)]
        st.rerun()

    options = visible_indices
    labels = []
    for i in options:
        status_mark = "✓" if confirmed_flags[i] else "·"
        attention_mark = " ⚠" if attention_flags[i] else ""
        labels.append(
            f"{status_mark}{attention_mark} {candidates[i].qualname}"
            f"  —  {candidates[i].benchmark_id}"
        )
    pos = options.index(st.session_state.cursor)
    # Keep the selectbox's session-state in lockstep with `cursor` so prev/next
    # don't desync the dropdown. Streamlit gives session_state precedence over
    # `index=` on rerun, so we overwrite it before rendering.
    st.session_state["picker"] = pos
    picked = st.sidebar.selectbox(
        "Jump to",
        list(range(len(options))),
        format_func=lambda j: labels[j],
        key="picker",
    )
    new_cursor = options[picked]
    if new_cursor != st.session_state.cursor:
        st.session_state.cursor = new_cursor
        st.rerun()
    return st.session_state.cursor


def main() -> None:
    st.set_page_config(page_title="Dualify gold-benchmark editor", layout="wide")
    st.title("Dualify gold-benchmark editor")

    dataset_path = st.sidebar.text_input(
        "Dataset path", value=str(DEFAULT_DATASET), key="dataset_path"
    )
    if not Path(dataset_path).exists():
        st.error(f"Dataset not found: {dataset_path}")
        return

    candidates = load_candidates(dataset_path)
    if not candidates:
        st.warning("No candidates after has_meaningful_informal_spec filter.")
        return

    idx = render_candidate_picker(candidates)
    candidate = candidates[idx]
    lifted = load_lifted(candidate)
    lifted_is_confirmed = is_confirmed(lifted)
    pre = prepopulate(candidate)

    bid = candidate.benchmark_id
    field_keys = {
        "spec": f"spec_{bid}",
        "profile": f"profile_{bid}",
        "infrag": f"infrag_{bid}",
        "pre": f"pre_{bid}",
        "post": f"post_{bid}",
        "notes": f"notes_{bid}",
        "attention": f"attention_{bid}",
    }

    if lifted:
        defaults = {
            "spec": lifted.get("informal_spec", pre["informal_spec_clean"]),
            "profile": lifted.get("profile", ""),
            "infrag": bool(lifted.get("in_fragment", True)),
            "pre": "\n".join(lifted.get("reference_pre", []) or []),
            "post": lifted.get("reference_post", "") or "",
            "notes": lifted.get("notes", ""),
            "attention": needs_attention(lifted),
        }
        if lifted_is_confirmed:
            origin_caption = "Defaults: from confirmed YAML."
        else:
            origin_caption = (
                f"Defaults: from unreviewed draft YAML "
                f"(status={lifted.get('status', 'unreviewed')!r}). "
                "Edit, then click Confirm to mark as reviewed."
            )
    else:
        defaults = {
            "spec": pre["informal_spec_clean"],
            "profile": "",
            "infrag": True,
            "pre": "\n".join(pre["reference_pre"]),
            "post": pre["reference_post"],
            "notes": "",
            "attention": False,
        }
        origin_caption = (
            "Defaults: stripped informal_spec + lifted normalized contract from the dataset."
        )

    # Seed each editable widget's session_state ONCE per browser session, then
    # let the widget itself own the value across reruns. This is the canonical
    # Streamlit pattern: never pass both `value=` and `key=`, because then a
    # rerun (e.g. triggered by Cmd+Enter in a textarea) can lose user edits.
    for name, key in field_keys.items():
        if key not in st.session_state:
            st.session_state[key] = defaults[name]

    left, right = st.columns([1, 1], gap="large")

    with left:
        st.subheader(candidate.qualname)
        st.caption(candidate.benchmark_id)
        if candidate.is_bug_example:
            st.warning(
                "Crosshair bug-detection example: the informal spec is intentionally "
                "broken and/or has verdict-leak comments. Not recommended for the "
                "[informal spec → formal spec] benchmark.",
                icon="🐛",
            )
        if not candidate.has_meaningful_informal_prose:
            st.warning(
                "No informal prose after stripping the formal directives and "
                "metadata markers (`NOTE:` / `TODO:` / etc.). Useful for the "
                "SMT half of the benchmark but not for [informal spec → formal spec].",
                icon="📭",
            )
        st.code(candidate.signature, language="python")
        st.markdown("**Source**")
        st.code(candidate.function_source, language="python")

        st.markdown("**Informal spec (raw, from dataset)**")
        st.info(candidate.informal_spec)

        if pre["stripped_directives"]:
            with st.expander(
                f"Stripped formal directives ({len(pre['stripped_directives'])})",
                expanded=False,
            ):
                for d in pre["stripped_directives"]:
                    st.code(d, language="python")
                st.caption(
                    "These were lifted into reference_pre / reference_post defaults on the right."
                )

        if pre["stripped_metadata_notes"]:
            with st.expander(
                f"Stripped metadata notes ({len(pre['stripped_metadata_notes'])})",
                expanded=False,
            ):
                for d in pre["stripped_metadata_notes"]:
                    st.code(d, language="python")
                st.caption("Removed from the cleaned informal_spec on the right.")

        if candidate.extra_context.strip():
            with st.expander("Extra context", expanded=False):
                st.code(candidate.extra_context)

        if candidate.raw_contract_blocks:
            with st.expander(
                f"Reference contract from dataset ({len(candidate.raw_contract_blocks)} blocks)",
                expanded=False,
            ):
                for block in candidate.raw_contract_blocks:
                    st.markdown(f"- **{block.get('kind', '?')}**: `{block.get('raw', '')}`")
                if candidate.normalized_domain_constraints:
                    st.markdown("**Normalized pre (auto):**")
                    for d in candidate.normalized_domain_constraints:
                        st.code(d, language="python")
                if candidate.normalized_postcondition:
                    st.markdown("**Normalized post (auto):**")
                    st.code(candidate.normalized_postcondition, language="python")

        st.markdown(
            f"**Allowed identifiers in formulas:** `{', '.join(sorted(candidate.allowed_names))}`"
        )

    with right:
        st.subheader("Gold annotation")
        st.caption(origin_caption)
        if defaults["attention"]:
            st.warning(
                "**Needs attention.** Set by the AI review or a previous editor "
                "session. Skim the notes below — typically: contract is hard to "
                "capture in-fragment, the lifted formula didn't validate, or "
                "the agent was unsure. Untick the box at the bottom once "
                "you're satisfied.",
                icon="⚠️",
            )
        st.caption(
            "Quantifiers over a collection's elements are admitted via Z3-native form: "
            "`ForAll([k], Implies(And(0 <= k, k < Length(ret)), P(ret[k])))` "
            "(and `Exists` likewise). Binder names introduced this way are auto-admitted."
        )

        st.text_area(
            "informal_spec (cleaned, editable — natural-language only)",
            height=120,
            key=field_keys["spec"],
        )

        st.text_area(
            "Profile (in-scope / out-of-scope / observable boundary)",
            height=120,
            key=field_keys["profile"],
        )

        st.checkbox(
            "Reference contract is expressible in the Dualify fragment",
            key=field_keys["infrag"],
        )

        st.text_area(
            "reference_pre  (one conjunct per line; use `ret` for the return value)",
            height=140,
            key=field_keys["pre"],
        )
        ref_pre_raw = st.session_state[field_keys["pre"]]
        pre_lines = parse_pre_lines(ref_pre_raw)
        pre_report = validate_many(pre_lines, candidate.allowed_names)
        _render_validation_block(pre_report, pre_lines, kind="pre")

        st.text_area(
            "reference_post  (single Boolean expression in `ret`)",
            height=100,
            key=field_keys["post"],
        )
        ref_post_raw = st.session_state[field_keys["post"]]
        post_lines = [ref_post_raw.strip()] if ref_post_raw.strip() else []
        post_report = validate_many(post_lines, candidate.allowed_names)
        _render_validation_block(post_report, post_lines, kind="post")

        st.text_area(
            "Notes (free form)",
            height=80,
            key=field_keys["notes"],
        )

        st.checkbox(
            "Needs attention (human reviewer should give this an extra look)",
            key=field_keys["attention"],
            help=(
                "Saved as `needs_attention: true` on the YAML. Picker labels "
                "show a ⚠ for these, and the sidebar has an 'Only show "
                "needs-attention' filter. Untick once you're satisfied."
            ),
        )

        spec = st.session_state[field_keys["spec"]]
        profile = st.session_state[field_keys["profile"]]
        in_fragment = st.session_state[field_keys["infrag"]]
        notes = st.session_state[field_keys["notes"]]
        attention = st.session_state[field_keys["attention"]]

        any_pre_errors = any(errors for _, _, errors in pre_report)
        any_post_errors = any(errors for _, _, errors in post_report)

        if st.button(
            "Reset to dataset prepopulation",
            help="Overwrites in-session edits for this card with the lifted defaults.",
            key=f"reset_{bid}",
        ):
            st.session_state[field_keys["spec"]] = pre["informal_spec_clean"]
            st.session_state[field_keys["profile"]] = ""
            st.session_state[field_keys["infrag"]] = True
            st.session_state[field_keys["pre"]] = "\n".join(pre["reference_pre"])
            st.session_state[field_keys["post"]] = pre["reference_post"]
            st.session_state[field_keys["notes"]] = ""
            st.session_state[field_keys["attention"]] = False
            st.rerun()

        if in_fragment:
            blocked = any_pre_errors or any_post_errors or not post_report
            block_reason = ""
            if any_pre_errors or any_post_errors:
                block_reason = "fix validation errors above"
            elif not post_report:
                block_reason = "reference_post is required when in_fragment=True"
        else:
            blocked = False
            block_reason = ""

        col_save, col_status = st.columns([1, 3])
        confirm_clicked = col_save.button(
            "Confirm",
            type="primary",
            disabled=blocked,
            use_container_width=True,
        )
        if blocked:
            col_status.warning(f"Confirm disabled: {block_reason}")
        elif lifted_is_confirmed:
            rel = yaml_path_for(candidate).relative_to(REPO_ROOT)
            col_status.caption(f"Confirmed at {rel}")
        elif lifted:
            rel = yaml_path_for(candidate).relative_to(REPO_ROOT)
            col_status.caption(f"Unreviewed draft at {rel}")
        else:
            col_status.caption("Unconfirmed")

        if confirm_clicked:
            payload: dict[str, Any] = {
                "benchmark_id": candidate.benchmark_id,
                "qualname": candidate.qualname,
                "file": candidate.file,
                "signature": candidate.signature,
                "arg_types": candidate.arg_types,
                "return_type": candidate.return_type,
                "informal_spec": spec.strip(),
                "informal_spec_raw": candidate.informal_spec,
                "function_source": candidate.function_source,
                "profile": profile.strip(),
                "in_fragment": in_fragment,
                "reference_pre": pre_lines,
                "reference_post": ref_post_raw.strip(),
                "notes": notes.strip(),
                "needs_attention": bool(attention),
                "status": "confirmed",
            }
            if in_fragment:
                payload["reference_normalized"] = {
                    "pre": [normalized for _, normalized, _ in pre_report],
                    "post": post_report[0][1] if post_report else "",
                }
            else:
                payload["reference_normalized"] = None
            written = save_yaml(candidate, payload)
            st.success(f"Confirmed → {written.relative_to(REPO_ROOT)}")
            st.rerun()

        if lifted:
            with st.expander("Danger zone", expanded=False):
                rel = yaml_path_for(candidate).relative_to(REPO_ROOT)
                label = "confirmed" if lifted_is_confirmed else "unreviewed draft"
                st.caption(
                    f"Delete the {label} YAML at `{rel}`. In-session edits "
                    "are preserved -- only the on-disk file is removed."
                )
                ack = st.checkbox(
                    "Confirm deletion",
                    key=f"ack_unconfirm_{bid}",
                )
                if st.button(
                    "Delete YAML",
                    disabled=not ack,
                    key=f"unconfirm_{bid}",
                ):
                    yaml_path_for(candidate).unlink(missing_ok=True)
                    st.session_state.pop(f"ack_unconfirm_{bid}", None)
                    st.rerun()


if __name__ == "__main__":
    main()
