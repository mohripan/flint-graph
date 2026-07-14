"""Recorded-evaluations evaluator.

The offline scorer runs against ``QueryEvaluation`` records captured from a real (or
deterministic) pipeline run, stored one per line as ``{"query_id", "evaluation"}``. This
decouples "capture from the live pipeline" (Phase 7) from "score, compare, and gate"
(offline, CI-friendly), and keeps the whole scoring path testable without live services.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from atlas_rag.evaluation.datasets import GoldenQuery
from atlas_rag.evaluation.experiment import QueryEvaluator
from atlas_rag.evaluation.metrics import QueryEvaluation


class RecordedEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    query_id: str
    evaluation: QueryEvaluation


def load_recorded_evaluations(path: Path) -> dict[str, QueryEvaluation]:
    recorded: dict[str, QueryEvaluation] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        record = RecordedEvaluation.model_validate_json(stripped)
        recorded[record.query_id] = record.evaluation
    return recorded


def recorded_evaluator(recorded: dict[str, QueryEvaluation]) -> QueryEvaluator:
    async def _evaluator(query: GoldenQuery) -> QueryEvaluation:
        if query.id not in recorded:
            raise KeyError(f"no recorded evaluation for query '{query.id}'")
        return recorded[query.id]

    return _evaluator
