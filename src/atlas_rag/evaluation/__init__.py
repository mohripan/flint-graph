"""AtlasRAG evaluation platform (Milestone 09).

Provider-neutral, offline building blocks: golden datasets, metrics, an experiment
runner over an injected evaluator, report I/O, and baseline/threshold comparison. See
docs/architecture/evaluation-contract.md.
"""

from atlas_rag.evaluation.baselines import (
    MetricThreshold,
    ThresholdViolation,
    check_regressions,
    check_thresholds,
    load_baseline,
    save_baseline,
)
from atlas_rag.evaluation.datasets import (
    DatasetMetadata,
    GoldenDataset,
    GoldenQuery,
    QueryType,
    load_dataset,
    load_metadata,
    load_queries,
)
from atlas_rag.evaluation.experiment import QueryEvaluator, run_experiment
from atlas_rag.evaluation.metrics import (
    QueryEvaluation,
    aggregate_metrics,
    answer_matches,
    hit_at_k,
    ndcg_at_k,
    per_query_metrics,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from atlas_rag.evaluation.report import (
    ExperimentReport,
    PerQueryResult,
    RunMetadata,
    read_report,
    write_report,
)

__all__ = [
    "DatasetMetadata",
    "ExperimentReport",
    "GoldenDataset",
    "GoldenQuery",
    "MetricThreshold",
    "PerQueryResult",
    "QueryEvaluation",
    "QueryEvaluator",
    "QueryType",
    "RunMetadata",
    "ThresholdViolation",
    "aggregate_metrics",
    "answer_matches",
    "check_regressions",
    "check_thresholds",
    "hit_at_k",
    "load_baseline",
    "load_dataset",
    "load_metadata",
    "load_queries",
    "ndcg_at_k",
    "per_query_metrics",
    "precision_at_k",
    "read_report",
    "recall_at_k",
    "reciprocal_rank",
    "run_experiment",
    "save_baseline",
    "write_report",
]
