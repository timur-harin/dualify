#!/usr/bin/env python3
"""Re-derive one campaign run report from its frozen transcript (offline).

Uses prompt-hash replay (``match_by_prompt=True``), the same mode as
``verify_reproducibility.py``. Writes a new timestamped JSON report beside
the transcript without deleting older reports.

Usage:
    PYTHONPATH=src python scripts/refresh_run_report_from_transcript.py \\
        results/campaigns/lifted_auto_eval__qwen_local/run_06
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dualify.aggregate import aggregate_runs, stable_cases  # noqa: E402
from dualify.io_utils import write_json  # noqa: E402
from dualify.runner import run_experiment  # noqa: E402
from dualify.transcript import ReplayLLMClient  # noqa: E402


def _latest_report(run_dir: Path, benchmark: str) -> Path | None:
    found = sorted(run_dir.glob(f"{benchmark}_*.json"), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def refresh_run(run_dir: Path, *, benchmark: str | None = None) -> Path:
    run_dir = run_dir.resolve()
    transcript = run_dir / "transcript.jsonl"
    if not transcript.is_file():
        raise FileNotFoundError(transcript)

    if benchmark is None:
        campaign = run_dir.parent
        agg = campaign / "aggregate.json"
        if agg.is_file():
            import json

            benchmark = json.loads(agg.read_text()).get("benchmark", "lifted_auto_eval")
        else:
            benchmark = "lifted_auto_eval"

    client = ReplayLLMClient.from_path(transcript, match_by_prompt=True)
    report = run_experiment(
        model="replay",
        base_url="",
        benchmark_name=benchmark,
        client_override=client,
        output_dir=run_dir,
    )
    out = _latest_report(run_dir, benchmark)
    if out is None:
        raise RuntimeError(f"no report written under {run_dir}")
    return out


def refresh_campaign(campaign_dir: Path, *, runs: list[str] | None = None) -> None:
    import json

    campaign_dir = campaign_dir.resolve()
    agg_path = campaign_dir / "aggregate.json"
    if not agg_path.is_file():
        raise FileNotFoundError(agg_path)
    meta = json.loads(agg_path.read_text())
    benchmark = meta.get("benchmark", "lifted_auto_eval")

    run_dirs = sorted(campaign_dir.glob("run_*"))
    if runs:
        wanted = set(runs)
        run_dirs = [d for d in run_dirs if d.name in wanted]

    reports: list[dict] = []
    for run_dir in run_dirs:
        latest = _latest_report(run_dir, benchmark)
        if latest is None:
            raise FileNotFoundError(f"missing report in {run_dir}")
        import json as _json

        reports.append(_json.loads(latest.read_text()))

    meta["aggregate"] = aggregate_runs(reports)
    meta["stability_genuine_equivalent"] = stable_cases(reports, "equivalent")
    write_json(agg_path, meta)
    print(f"updated {agg_path}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="run_NN directory or campaign directory")
    parser.add_argument(
        "--campaign",
        action="store_true",
        help="Treat path as campaign dir: refresh listed runs and rewrite aggregate.json",
    )
    parser.add_argument(
        "--run",
        action="append",
        default=[],
        help="With --campaign, only refresh these run dirs (e.g. run_06)",
    )
    parser.add_argument("--benchmark", default="", help="Override benchmark name")
    args = parser.parse_args()

    path = Path(args.path)
    if args.campaign:
        refresh_campaign(path, runs=args.run or None)
        return 0

    out = refresh_run(path, benchmark=args.benchmark or None)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
