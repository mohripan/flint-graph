"""FlintGraph evaluation platform (Milestone 09).

Provider-neutral, offline building blocks: golden datasets, metrics, an experiment
runner over an injected evaluator, report I/O, and baseline/threshold comparison. See
docs/architecture/evaluation-contract.md.
"""

from flint_graph.evaluation.baselines import (
    MetricThreshold,
    ThresholdViolation,
    check_regressions,
    check_thresholds,
    load_baseline,
    save_baseline,
)
from flint_graph.evaluation.comparison import comparison_table, run_comparison
from flint_graph.evaluation.datasets import (
    DatasetMetadata,
    GoldenDataset,
    GoldenQuery,
    QueryType,
    load_dataset,
    load_metadata,
    load_queries,
)
from flint_graph.evaluation.experiment import QueryEvaluator, run_experiment
from flint_graph.evaluation.experiments import ExperimentConfig, load_experiment
from flint_graph.evaluation.metrics import (
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
from flint_graph.evaluation.recorded import (
    RecordedEvaluation,
    load_recorded_evaluations,
    recorded_evaluator,
)
from flint_graph.evaluation.report import (
    ExperimentReport,
    PerQueryResult,
    RunMetadata,
    read_report,
    write_report,
)

__all__ = [
    "DatasetMetadata",
    "ExperimentConfig",
    "ExperimentReport",
    "GoldenDataset",
    "GoldenQuery",
    "MetricThreshold",
    "PerQueryResult",
    "QueryEvaluation",
    "QueryEvaluator",
    "QueryType",
    "RecordedEvaluation",
    "RunMetadata",
    "ThresholdViolation",
    "aggregate_metrics",
    "answer_matches",
    "check_regressions",
    "check_thresholds",
    "comparison_table",
    "hit_at_k",
    "load_baseline",
    "load_dataset",
    "load_experiment",
    "load_metadata",
    "load_queries",
    "load_recorded_evaluations",
    "ndcg_at_k",
    "per_query_metrics",
    "precision_at_k",
    "read_report",
    "recall_at_k",
    "reciprocal_rank",
    "recorded_evaluator",
    "run_comparison",
    "run_experiment",
    "save_baseline",
    "write_report",
]
