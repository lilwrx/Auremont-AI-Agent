"""Grade recorded pipeline runs and write report.json.

The "run graders" step of the eval flywheel. Reads the JSONL traces written by
`backend/core/tracing.py`, applies `eval/graders.py`, and writes a machine-readable
report plus a short human summary.

Usage:
    python scripts/run_eval.py                        # eval/runs.jsonl -> eval/results/
    python scripts/run_eval.py --runs path/to.jsonl
    python scripts/run_eval.py --fail-under 0.9       # non-zero exit for CI

`--fail-under` is what makes this a regression gate rather than a report: wire it into CI
and a change that drops the pass rate stops being something a reviewer has to notice.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.tracing import read_runs  # noqa: E402
from eval.graders import build_report  # noqa: E402

DEFAULT_RUNS = Path("eval/runs.jsonl")
DEFAULT_OUT = Path("eval/results")


def _summarise(report: dict) -> str:
    lines = [
        f"Runs graded: {report['runs']}",
        f"Pass rate:   {report['pass_rate']:.1%} ({report['passed']} passed, {report['failed']} failed)",
    ]

    latency = report["latency_ms"]
    if latency["p50"] is not None:
        lines.append(f"Latency:     p50 {latency['p50']}ms | p95 {latency['p95']}ms | max {latency['max']}ms")

    if report["failure_modes"]:
        lines.append("\nFailure modes:")
        for mode, count in sorted(report["failure_modes"].items(), key=lambda item: -item[1]):
            lines.append(f"  {count:4}  {mode}")

    failing = {name: stats for name, stats in report["graders"].items() if stats["failed"]}
    if failing:
        lines.append("\nFailing graders:")
        for name, stats in sorted(failing.items(), key=lambda item: -item[1]["failed"]):
            lines.append(f"  {stats['failed']:4}/{stats['total']}  {name}")
            for example in stats["examples"]:
                lines.append(f"          {example}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=Path, default=DEFAULT_RUNS, help="JSONL of recorded runs")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="directory for report.json")
    parser.add_argument(
        "--fail-under",
        type=float,
        default=None,
        metavar="RATE",
        help="exit non-zero when the pass rate falls below RATE (0-1), for CI",
    )
    args = parser.parse_args()

    runs = read_runs(args.runs)
    if not runs:
        print(
            f"No runs found in {args.runs}.\n"
            "Record some first: set TRACING_ENABLED=true, ask the agent a few questions, then re-run.",
            file=sys.stderr,
        )
        return 1

    report = build_report(runs)

    args.out.mkdir(parents=True, exist_ok=True)
    report_path = args.out / "report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(_summarise(report))
    print(f"\nWrote {report_path}")

    if args.fail_under is not None and report["pass_rate"] < args.fail_under:
        print(
            f"\nFAIL: pass rate {report['pass_rate']:.1%} is below the required {args.fail_under:.1%}.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
