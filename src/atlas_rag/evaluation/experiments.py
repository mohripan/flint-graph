"""Experiment definitions (``evals/experiments/<name>.yaml``).

An experiment names one or more provider configurations, the retrieval modes to ablate,
the k values to score, and the regression thresholds to enforce. Provider configs are
opaque here — they are consumed by the live-capture evaluator (Phase 7); the offline
scorer only needs ``k_values`` and ``thresholds``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from atlas_rag.evaluation.baselines import MetricThreshold


class ExperimentConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset: str = Field(min_length=1)
    configs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    retrieval_modes: list[str] = Field(default_factory=list)
    k_values: list[int] = Field(default_factory=lambda: [1, 5, 10])
    thresholds: dict[str, MetricThreshold] = Field(default_factory=dict)


def load_experiment(path: Path) -> ExperimentConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ExperimentConfig.model_validate(raw)
