"""Offline experiment runner.

Runs each dataset query through an injected ``QueryEvaluator`` (the system under test),
computes per-query and aggregate metrics, and assembles an ``ExperimentReport``. The
evaluator is provider-neutral: tests pass a fake, and the real pipeline-backed evaluator
is wired in a later phase. The runner itself performs no I/O and no model calls.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from flint_graph.evaluation.datasets import GoldenDataset, GoldenQuery
from flint_graph.evaluation.metrics import (
    QueryEvaluation,
    aggregate_metrics,
    per_query_metrics,
)
from flint_graph.evaluation.report import ExperimentReport, PerQueryResult, RunMetadata

QueryEvaluator = Callable[[GoldenQuery], Awaitable[QueryEvaluation]]


async def run_experiment(
    *,
    dataset: GoldenDataset,
    evaluator: QueryEvaluator,
    config_name: str,
    created_at: str,
    k_values: list[int] | None = None,
    git_sha: str | None = None,
    coverage: dict[str, Any] | None = None,
) -> ExperimentReport:
    resolved_k = k_values or [1, 5, 10]
    pairs: list[tuple[GoldenQuery, QueryEvaluation]] = []
    per_query: list[PerQueryResult] = []

    for query in dataset.queries:
        evaluation = await evaluator(query)
        pairs.append((query, evaluation))
        per_query.append(
            PerQueryResult(
                query_id=query.id,
                query_type=query.query_type,
                abstained=evaluation.abstained,
                metrics=per_query_metrics(query, evaluation, resolved_k),
                evaluation=evaluation,
            )
        )

    run = RunMetadata(
        dataset_name=dataset.metadata.name,
        dataset_version=dataset.metadata.version,
        config_name=config_name,
        query_count=len(dataset.queries),
        k_values=resolved_k,
        created_at=created_at,
        git_sha=git_sha,
        coverage=coverage or {},
    )
    return ExperimentReport(
        run=run,
        aggregate=aggregate_metrics(pairs, resolved_k),
        per_query=per_query,
    )
