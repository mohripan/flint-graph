"""Experiment report models and file I/O.

Reports are plain JSON files under ``evals/reports/<name>/`` so quality history is
versioned and diffable in PRs (ADR 0010). Run metadata such as ``created_at`` and
``git_sha`` is injected by the caller — kept out of the pure core for reproducibility.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from flint_graph.evaluation.metrics import QueryEvaluation


class RunMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_name: str
    dataset_version: int
    config_name: str
    query_count: int = Field(ge=0)
    k_values: list[int] = Field(default_factory=list)
    created_at: str
    git_sha: str | None = None
    coverage: dict[str, Any] = Field(default_factory=dict)


class PerQueryResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    query_id: str
    query_type: str
    abstained: bool
    metrics: dict[str, float] = Field(default_factory=dict)
    evaluation: QueryEvaluation


class ExperimentReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    run: RunMetadata
    aggregate: dict[str, float] = Field(default_factory=dict)
    per_query: list[PerQueryResult] = Field(default_factory=list)


def write_report(report: ExperimentReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")


def read_report(path: Path) -> ExperimentReport:
    return ExperimentReport.model_validate_json(path.read_text(encoding="utf-8"))
