"""Regression thresholds and baseline comparison.

Two independent gates: absolute thresholds (``min``/``max`` floors from an experiment
definition) and baseline regression (drift beyond a tolerance versus accepted values).
Baselines change only through an explicit, reviewed update (ADR 0010) — this module
never mutates them implicitly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Metrics where a lower value is better; everything else is treated as higher-is-better.
LOWER_IS_BETTER: frozenset[str] = frozenset(
    {
        "unsupported_claim_count",
        "latency_ms_p50",
        "latency_ms_p95",
        "input_tokens_total",
        "output_tokens_total",
        "estimated_cost_usd_total",
    }
)


class MetricThreshold(BaseModel):
    model_config = ConfigDict(frozen=True)

    min: float | None = None
    max: float | None = None


class ThresholdViolation(BaseModel):
    model_config = ConfigDict(frozen=True)

    metric: str
    kind: Literal["min", "max", "regression", "missing"]
    limit: float
    actual: float | None
    detail: str = Field(default="", max_length=500)


def check_thresholds(
    aggregate: dict[str, float], thresholds: dict[str, MetricThreshold]
) -> list[ThresholdViolation]:
    violations: list[ThresholdViolation] = []
    for metric, threshold in thresholds.items():
        if metric not in aggregate:
            limit = threshold.min if threshold.min is not None else (threshold.max or 0.0)
            violations.append(
                ThresholdViolation(
                    metric=metric,
                    kind="missing",
                    limit=limit,
                    actual=None,
                    detail="metric not present in the report aggregate",
                )
            )
            continue
        value = aggregate[metric]
        if threshold.min is not None and value < threshold.min:
            violations.append(
                ThresholdViolation(
                    metric=metric, kind="min", limit=threshold.min, actual=value
                )
            )
        if threshold.max is not None and value > threshold.max:
            violations.append(
                ThresholdViolation(
                    metric=metric, kind="max", limit=threshold.max, actual=value
                )
            )
    return violations


def check_regressions(
    aggregate: dict[str, float],
    baseline: dict[str, float],
    *,
    tolerance: float = 0.0,
) -> list[ThresholdViolation]:
    violations: list[ThresholdViolation] = []
    for metric, baseline_value in baseline.items():
        if metric not in aggregate:
            violations.append(
                ThresholdViolation(
                    metric=metric,
                    kind="missing",
                    limit=baseline_value,
                    actual=None,
                    detail="baseline metric not present in the report aggregate",
                )
            )
            continue
        value = aggregate[metric]
        if metric in LOWER_IS_BETTER:
            limit = baseline_value + tolerance
            if value > limit:
                violations.append(
                    ThresholdViolation(
                        metric=metric,
                        kind="regression",
                        limit=limit,
                        actual=value,
                        detail="rose above baseline + tolerance (lower is better)",
                    )
                )
        else:
            limit = baseline_value - tolerance
            if value < limit:
                violations.append(
                    ThresholdViolation(
                        metric=metric,
                        kind="regression",
                        limit=limit,
                        actual=value,
                        detail="dropped below baseline - tolerance (higher is better)",
                    )
                )
    return violations


def load_baseline(path: Path) -> dict[str, float]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(key): float(value) for key, value in raw.items()}


def save_baseline(path: Path, aggregate: dict[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = {key: aggregate[key] for key in sorted(aggregate)}
    path.write_text(json.dumps(ordered, indent=2), encoding="utf-8")
