"""``flint-graph-eval`` — offline scoring, comparison, and regression gating.

Scores a golden dataset against recorded ``QueryEvaluation`` records (captured from a
pipeline run), writes a JSON report, and gates on absolute thresholds (from an experiment
definition) and/or baseline regressions. All commands are offline and deterministic;
capturing evaluations from the live pipeline is a separate step (Phase 7 live gate).
"""

from __future__ import annotations

import argparse
import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx

from flint_graph.cli.nightly import register_nightly
from flint_graph.evaluation.baselines import (
    ThresholdViolation,
    check_regressions,
    check_thresholds,
    load_baseline,
    save_baseline,
)
from flint_graph.evaluation.capture import CaptureManifest, capture_dataset
from flint_graph.evaluation.comparison import comparison_table, run_comparison
from flint_graph.evaluation.datasets import load_dataset
from flint_graph.evaluation.experiment import run_experiment
from flint_graph.evaluation.experiments import load_experiment
from flint_graph.evaluation.prepare import load_corpus, prepare_corpus, verify_prepared_corpus
from flint_graph.evaluation.recorded import load_recorded_evaluations, recorded_evaluator
from flint_graph.evaluation.report import ExperimentReport, read_report, write_report

_DEFAULT_K = [1, 5, 10]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _format_aggregate(aggregate: dict[str, float]) -> str:
    return "\n".join(f"  {metric}: {value:.4f}" for metric, value in sorted(aggregate.items()))


def _print_violations(violations: list[ThresholdViolation]) -> None:
    for violation in violations:
        actual = "n/a" if violation.actual is None else f"{violation.actual:.4f}"
        print(
            f"FAIL {violation.metric}: {violation.kind} limit={violation.limit:.4f} actual={actual}"
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
        violations += check_regressions(report.aggregate, baseline, tolerance=args.tolerance)

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


def _api_connection_options(args: argparse.Namespace) -> tuple[str, dict[str, str]]:
    url = httpx.URL(args.base_url)
    local = url.host in {"localhost", "127.0.0.1", "::1"}
    if (
        url.scheme not in {"https", "http"}
        or not url.host
        or (url.scheme == "http" and not local)
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("Evaluation API access requires HTTPS or credential-free loopback HTTP.")
    token = os.getenv(args.token_env)
    return str(url), {"Authorization": f"Bearer {token}"} if token else {}


def prepare_command(args: argparse.Namespace) -> int:
    output = Path(args.output)
    try:
        if output.exists() or output.is_symlink():
            raise ValueError("Manifest output already exists; choose a new path.")
        if (args.workspace_id is None) != (args.index_version_id is None):
            raise ValueError("Existing preparation requires both workspace and active index UUIDs.")
        if args.verify_only and args.workspace_id is None:
            raise ValueError("Verify-only requires both workspace and active index UUIDs.")
        base_url, headers = _api_connection_options(args)
        dataset = load_dataset(Path(args.dataset))
        sources = load_corpus(Path(args.dataset), dataset)

        async def prepare() -> str:
            async with httpx.AsyncClient(
                base_url=base_url,
                headers=headers,
                timeout=60,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                if args.verify_only:
                    manifest = await verify_prepared_corpus(
                        client,
                        dataset,
                        sources,
                        workspace_id=args.workspace_id,
                        index_version_id=args.index_version_id,
                        timeout_seconds=args.prepare_timeout,
                    )
                    return manifest.model_dump_json(indent=2) + "\n"
                manifest = await prepare_corpus(
                    client,
                    dataset,
                    sources,
                    timeout_seconds=args.prepare_timeout,
                    workspace_id=args.workspace_id,
                    index_version_id=args.index_version_id,
                    on_workspace_created=lambda workspace_id: print(
                        f"Created evaluation workspace {workspace_id}"
                    ),
                )
            return manifest.model_dump_json(indent=2) + "\n"

        content = asyncio.run(prepare())
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as manifest_file:
            manifest_file.write(content)
        operation = "Verified existing" if args.verify_only else "Prepared"
        print(f"{operation} {len(sources)} documents; wrote capture manifest to {output}")
        return 0
    except httpx.HTTPError as exc:
        print(f"Preparation failed: {type(exc).__name__}. Inspect the created workspace/jobs.")
        return 1
    except (ValueError, OSError) as exc:
        print(f"Preparation failed: {exc}")
        return 1


def capture_command(args: argparse.Namespace) -> int:
    output = Path(args.output)
    try:
        if output.exists() or output.is_symlink():
            raise ValueError("Capture output already exists; choose a new recording path.")
        base_url, headers = _api_connection_options(args)
        dataset = load_dataset(Path(args.dataset))
        manifest = CaptureManifest.model_validate_json(
            Path(args.manifest).read_text(encoding="utf-8")
        )

        async def capture() -> str:
            async with httpx.AsyncClient(
                base_url=base_url,
                headers=headers,
                timeout=args.query_timeout,
                follow_redirects=False,
            ) as client:
                records = await capture_dataset(
                    client,
                    dataset,
                    manifest,
                    git_sha=args.git_sha,
                    query_timeout_seconds=args.query_timeout,
                )
            return "".join(record.model_dump_json() + "\n" for record in records)

        content = asyncio.run(capture())
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as recording:
            recording.write(content)
        print(f"Captured {len(dataset.queries)} fresh query evaluations to {output}")
        return 0
    except httpx.HTTPError as exc:
        # Do not echo error response payloads, authorization headers or credential-bearing URLs.
        print(f"Capture failed: {type(exc).__name__}. Inspect the server-side run/events.")
        return 1
    except (ValueError, OSError, TimeoutError) as exc:
        print(f"Capture failed: {exc}")
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flint-graph-eval")
    subparsers = parser.add_subparsers(dest="command", required=True)
    register_nightly(subparsers)

    prepare_parser = subparsers.add_parser(
        "prepare", help="ingest a fresh dedicated evaluation corpus"
    )
    prepare_parser.add_argument("--dataset", required=True)
    prepare_parser.add_argument("--base-url", required=True)
    prepare_parser.add_argument("--output", required=True, help="new capture manifest JSON")
    prepare_parser.add_argument("--token-env", default="FLINT_GRAPH_EVAL_TOKEN")
    prepare_parser.add_argument("--prepare-timeout", type=float, default=600.0)
    prepare_parser.add_argument("--workspace-id", type=UUID, default=None)
    prepare_parser.add_argument("--index-version-id", type=UUID, default=None)
    prepare_parser.add_argument(
        "--verify-only", action="store_true", help="Verify existing documents without uploads"
    )
    prepare_parser.set_defaults(func=prepare_command)

    capture_parser = subparsers.add_parser("capture", help="capture fresh public-API query runs")
    capture_parser.add_argument("--dataset", required=True)
    capture_parser.add_argument(
        "--manifest", required=True, help="tenant and golden-label mappings"
    )
    capture_parser.add_argument("--base-url", required=True)
    capture_parser.add_argument(
        "--output", required=True, help="new JSONL recording (never overwritten)"
    )
    capture_parser.add_argument("--token-env", default="FLINT_GRAPH_EVAL_TOKEN")
    capture_parser.add_argument("--query-timeout", type=float, default=300.0)
    capture_parser.add_argument("--git-sha", default=None)
    capture_parser.set_defaults(func=capture_command)

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

    compare_parser = subparsers.add_parser("compare", help="score several evaluators side by side")
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
