"""``atlas-eval`` — offline scoring, comparison, and regression gating.

Scores a golden dataset against recorded ``QueryEvaluation`` records (captured from a
pipeline run), writes a JSON report, and gates on absolute thresholds (from an experiment
definition) and/or baseline regressions. All commands are offline and deterministic;
capturing evaluations from the live pipeline is a separate step (Phase 7 live gate).
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path

from atlas_rag.evaluation.baselines import (
    ThresholdViolation,
    check_regressions,
    check_thresholds,
    load_baseline,
    save_baseline,
)
from atlas_rag.evaluation.comparison import comparison_table, run_comparison
from atlas_rag.evaluation.datasets import load_dataset
from atlas_rag.evaluation.experiment import run_experiment
from atlas_rag.evaluation.experiments import load_experiment
from atlas_rag.evaluation.recorded import load_recorded_evaluations, recorded_evaluator
from atlas_rag.evaluation.report import ExperimentReport, read_report, write_report

_DEFAULT_K = [1, 5, 10]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _format_aggregate(aggregate: dict[str, float]) -> str:
    return "\n".join(f"  {metric}: {value:.4f}" for metric, value in sorted(aggregate.items()))


def _print_violations(violations: list[ThresholdViolation]) -> None:
    for violation in violations:
        actual = "n/a" if violation.actual is None else f"{violation.actual:.4f}"
        print(
            f"FAIL {violation.metric}: {violation.kind} "
            f"limit={violation.limit:.4f} actual={actual}"
        )


def run_command(args: argparse.Namespace) -> int:
    dataset = load_dataset(Path(args.dataset))
    recorded = load_recorded_evaluations(Path(args.evaluations))
    k_values: list[int] = args.k or _DEFAULT_K
    created_at: str = args.created_at or _now_iso()

    report = asyncio.run(
        run_experiment(
            dataset=dataset,
            evaluator=recorded_evaluator(recorded),
            config_name=args.config_name,
            created_at=created_at,
            k_values=k_values,
            git_sha=args.git_sha,
        )
    )

    if args.report:
        write_report(report, Path(args.report))
    print(f"{report.run.config_name} @ {report.run.dataset_name} v{report.run.dataset_version}")
    print(_format_aggregate(report.aggregate))

    violations: list[ThresholdViolation] = []
    if args.experiment:
        experiment = load_experiment(Path(args.experiment))
        violations += check_thresholds(report.aggregate, experiment.thresholds)
    if args.baseline:
        baseline = load_baseline(Path(args.baseline))
        violations += check_regressions(
            report.aggregate, baseline, tolerance=args.tolerance
        )

    if violations:
        _print_violations(violations)
        return 1
    return 0


def compare_command(args: argparse.Namespace) -> int:
    dataset = load_dataset(Path(args.dataset))
    k_values: list[int] = args.k or _DEFAULT_K
    created_at: str = args.created_at or _now_iso()

    evaluators = {}
    for spec in args.evaluations:
        name, separator, path = spec.partition("=")
        if not separator:
            print(f"invalid --evaluations spec '{spec}' (expected name=path)")
            return 2
        evaluators[name] = recorded_evaluator(load_recorded_evaluations(Path(path)))

    reports = asyncio.run(
        run_comparison(
            dataset=dataset,
            evaluators=evaluators,
            created_at=created_at,
            k_values=k_values,
        )
    )

    if args.report_dir:
        report_dir = Path(args.report_dir)
        for name, report in reports.items():
            write_report(report, report_dir / f"{name}.json")

    table = comparison_table(reports)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(table, encoding="utf-8")
    print(table, end="")
    return 0


def baseline_command(args: argparse.Namespace) -> int:
    report: ExperimentReport = read_report(Path(args.report))
    save_baseline(Path(args.baseline), report.aggregate)
    print(f"wrote baseline for {len(report.aggregate)} metrics to {args.baseline}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atlas-eval")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="score a dataset and gate on thresholds")
    run_parser.add_argument("--dataset", required=True, help="dataset directory")
    run_parser.add_argument("--evaluations", required=True, help="recorded evaluations JSONL")
    run_parser.add_argument("--config-name", default="recorded")
    run_parser.add_argument("--k", type=int, action="append")
    run_parser.add_argument("--report", default=None, help="write the JSON report here")
    run_parser.add_argument("--experiment", default=None, help="experiment YAML for thresholds")
    run_parser.add_argument("--baseline", default=None, help="baseline JSON for regressions")
    run_parser.add_argument("--tolerance", type=float, default=0.0)
    run_parser.add_argument("--git-sha", default=None)
    run_parser.add_argument("--created-at", default=None)
    run_parser.set_defaults(func=run_command)

    compare_parser = subparsers.add_parser(
        "compare", help="score several evaluators side by side"
    )
    compare_parser.add_argument("--dataset", required=True)
    compare_parser.add_argument(
        "--evaluations", action="append", required=True, help="name=path (repeatable)"
    )
    compare_parser.add_argument("--k", type=int, action="append")
    compare_parser.add_argument("--output", default=None, help="write comparison markdown here")
    compare_parser.add_argument("--report-dir", default=None, help="write per-config reports here")
    compare_parser.add_argument("--created-at", default=None)
    compare_parser.set_defaults(func=compare_command)

    baseline_parser = subparsers.add_parser("baseline", help="manage baselines")
    baseline_sub = baseline_parser.add_subparsers(dest="baseline_command", required=True)
    update_parser = baseline_sub.add_parser("update", help="write a baseline from a report")
    update_parser.add_argument("--report", required=True)
    update_parser.add_argument("--baseline", required=True)
    update_parser.set_defaults(func=baseline_command)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
