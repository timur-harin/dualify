# Verified Dataset Sources for Dualify Benchmarking

Below is a concise, verified list of sources relevant for extracting formal specifications from code and documentation. Python-first sources are prioritized, with additional non-Python formal benchmarks included for broader coverage and stress testing.

| Source | Type | Language(s) | Dataset size | Explicit contracts/specs in code | Contents | Direct link |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Python-by-Contract Corpus | Contracted code corpus | Python | 514 functions | Yes (`icontract`) | Functions with `icontract` pre/postconditions | https://github.com/mristin/python-by-contract-corpus |
| CodeSpecBench | Specification benchmark | Python | 2,494 function-level tasks (+ repo track) | Partial (executable spec functions, not always inline contracts) | `Func` + `Repo` tracks, executable specs, test-based evaluation | https://github.com/SparksofAGI/CodeSpecBench |
| EvalPlus (HumanEval+/MBPP+) | Assert-based benchmark | Python | HumanEval+ + MBPP+ (large benchmark suite) | No (tests/assert oracles, no inline contracts) | Extended tests and `assert` oracles (executable specs) | https://github.com/evalplus/evalplus |
| CrossHair examples | Example corpus | Python | ~80 example files (corpus-style) | Yes (PEP316/icontract/deal) | PEP316/icontract/deal contract examples | https://github.com/pschanely/CrossHair/tree/main/crosshair/examples |
| SWE-bench Verified (as Repo-track source) | Repository benchmark source | Mostly Python repos | Repository-level issue tasks (size varies by release) | No (issue/patch tasks, not contract-annotated corpus) | Real issue-based OSS tasks | https://github.com/SparksofAGI/CodeSpecBench |
| VERINA | Verifiable code generation benchmark | Lean 4 | 189 tasks | Yes (formal specs/theorems) | Description, code, specs, tests | https://github.com/sunblaze-ucb/verina |
| CLEVER | Formal verification benchmark | Lean | 161 tasks | Yes (formal logical specs) | Strict formal spec reasoning tasks | https://github.com/trishullab/clever |
| FVAPPS | Large formal benchmark | Lean 4 (+APPS) | 4,715+ samples | Yes (formal theorem/spec tasks) | Formally verifiable programming tasks | https://github.com/quinn-dougherty/fvapps |
| DafnyBench | Formal verification benchmark | Dafny | ~750-782 programs (~53k LoC) | Yes (`requires/ensures`) | Tasks with `requires/ensures` | https://github.com/sun-wendy/DafnyBench |
| FStarDataSet | Proof-oriented dataset | F* | ~32k definitions (v1), ~54k (v2) | Yes (types as specs) | Type-driven formal specification data | https://huggingface.co/datasets/microsoft/FStarDataSet |
| SV-Benchmarks (SV-COMP 2025) | Canonical verification benchmark | C, Java, Horn/SMT | Very large multi-category task set | Partial (task-level formal properties, not always inline contracts) | `.prp` properties + `.yml` task defs | https://gitlab.com/sosy-lab/benchmarking/sv-benchmarks/tree/svcomp25 |
| SV-Benchmarks (archival snapshot) | Reproducibility snapshot | C, Java, Horn/SMT | Snapshot of SV-COMP 2025 benchmark set | Partial (same as SV-Benchmarks) | Fixed release for repeatable experiments | https://zenodo.org/records/15012096 |
| Frama-C Open Source Case Studies | Formal analysis case corpus | C (some ACSL) | Dozens of case-study projects (corpus-style) | Partial (some cases have ACSL, many without full contracts) | Open-source cases for formal analysis workflows | https://git.frama-c.com/pub/open-source-case-studies |
| VerifyThis (archive + LTC) | Challenge archive | Multi-language | Yearly challenge sets (typically 3-4 tasks/year) | Partial (problem statements + external proofs/specs) | Archive of verification tasks and long-term challenges | https://verifythis.github.io/archive |
| VeHa 2025 | Contest tasks and artifacts | SPIN/TLA+/Isabelle/Why3/Rocq | Contest task set (edition-based) | Partial (depends on specific task/tool) | Competition tasks, outcomes, partially open solutions | https://sites.google.com/view/veha2025/ |
| arXiv 2310.02154 (Program Structure Aware Precondition Generation) | Paper + claimed dataset | Java | ~18k `(method, precondition)` pairs (claimed) | Yes (generated preconditions) | Precondition generation dataset claim | https://arxiv.org/pdf/2310.02154 |
