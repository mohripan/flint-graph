"""Run a dataset under several named evaluators and render a comparison.

Retrieval ablations and model/prompt comparisons are the same shape: a set of named
evaluators (one per retrieval mode, or one per provider config) scored over the same
dataset, presented side by side.
"""

from __future__ import annotations

from flint_graph.evaluation.datasets import GoldenDataset
from flint_graph.evaluation.experiment import QueryEvaluator, run_experiment
from flint_graph.evaluation.report import ExperimentReport


async def run_comparison(
    *,
    dataset: GoldenDataset,
    evaluators: dict[str, QueryEvaluator],
    created_at: str,
    k_values: list[int] | None = None,
    git_sha: str | None = None,
) -> dict[str, ExperimentReport]:
    reports: dict[str, ExperimentReport] = {}
    for name, evaluator in evaluators.items():
        reports[name] = await run_experiment(
            dataset=dataset,
            evaluator=evaluator,
            config_name=name,
            created_at=created_at,
            k_values=k_values,
            git_sha=git_sha,
        )
    return reports


def comparison_table(
    reports: dict[str, ExperimentReport], *, metrics: list[str] | None = None
) -> str:
    names = list(reports.keys())
    if metrics is None:
        keys: set[str] = set()
        for report in reports.values():
            keys.update(report.aggregate.keys())
        metrics = sorted(keys)

    header = "| metric | " + " | ".join(names) + " |"
    separator = "| --- | " + " | ".join("---" for _ in names) + " |"
    rows = [header, separator]
    for metric in metrics:
        cells: list[str] = []
        for name in names:
            value = reports[name].aggregate.get(metric)
            cells.append(f"{value:.4f}" if value is not None else "-")
        rows.append(f"| {metric} | " + " | ".join(cells) + " |")
    return "\n".join(rows) + "\n"
