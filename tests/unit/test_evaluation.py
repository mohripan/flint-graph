from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from flint_graph.evaluation import (
    DatasetMetadata,
    ExperimentReport,
    GoldenDataset,
    GoldenQuery,
    MetricThreshold,
    QueryEvaluation,
    aggregate_metrics,
    answer_matches,
    check_regressions,
    check_thresholds,
    hit_at_k,
    load_baseline,
    load_dataset,
    ndcg_at_k,
    per_query_metrics,
    precision_at_k,
    read_report,
    recall_at_k,
    reciprocal_rank,
    run_experiment,
    save_baseline,
    write_report,
)


def _factoid(
    query_id: str,
    relevant: list[str],
    expected: str,
    must_cite_sources: list[str] | None = None,
) -> GoldenQuery:
    return GoldenQuery(
        id=query_id,
        query=f"query {query_id}",
        query_type="factoid",
        expected_answer=expected,
        relevant_chunk_ids=relevant,
        must_cite_sources=must_cite_sources or [],
    )


# --- Retrieval metric functions ---


def test_retrieval_metric_functions_on_known_inputs() -> None:
    relevant = ["c-a"]
    retrieved = ["c-a", "c-x"]

    assert recall_at_k(relevant, retrieved, 1) == 1.0
    assert precision_at_k(relevant, retrieved, 1) == 1.0
    assert precision_at_k(relevant, retrieved, 2) == 0.5
    assert hit_at_k(relevant, retrieved, 1) == 1.0
    assert reciprocal_rank(relevant, retrieved) == 1.0
    assert ndcg_at_k(relevant, retrieved, 1) == 1.0

    # relevant only at rank 2
    assert reciprocal_rank(["c-b"], ["c-y", "c-b"]) == 0.5
    assert hit_at_k(["c-b"], ["c-y", "c-b"], 1) == 0.0
    assert recall_at_k([], ["c-a"], 5) == 0.0


def test_answer_matches_normalizes_punctuation_and_case() -> None:
    assert answer_matches("Berlin", "It is Berlin.")
    assert answer_matches("berlin", "BERLIN")
    assert not answer_matches("Paris", "Lyon")
    assert not answer_matches("", "anything")


# --- Per-query metrics ---


def test_per_query_metrics_for_answered_factoid() -> None:
    query = _factoid("q1", ["c-a"], "Berlin", must_cite_sources=["chunk-a"])
    evaluation = QueryEvaluation(
        retrieved_chunk_ids=["c-a", "c-x"],
        answer_text="It is Berlin.",
        cited_source_ids=["chunk-a"],
        supported_claim_count=2,
    )

    metrics = per_query_metrics(query, evaluation, [1])

    assert metrics["abstention_correct"] == 1.0
    assert metrics["recall@1"] == 1.0
    assert metrics["mrr"] == 1.0
    assert metrics["supported_claim_ratio"] == 1.0
    assert metrics["unsupported_claim_count"] == 0.0
    assert metrics["citation_valid"] == 1.0
    assert metrics["answer_match"] == 1.0
    assert metrics["must_cite_satisfied"] == 1.0


def test_per_query_metrics_for_expected_abstention() -> None:
    query = GoldenQuery(id="q3", query="unknown", query_type="abstain_expected")
    evaluation = QueryEvaluation(abstained=True)

    metrics = per_query_metrics(query, evaluation, [1])

    assert metrics["abstention_correct"] == 1.0
    assert "supported_claim_ratio" not in metrics
    assert "answer_match" not in metrics


# --- Aggregate ---


def _sample_pairs() -> list[tuple[GoldenQuery, QueryEvaluation]]:
    q1 = _factoid("q1", ["c-a"], "Berlin", must_cite_sources=["chunk-a"])
    q2 = _factoid("q2", ["c-b"], "Paris")
    q3 = GoldenQuery(id="q3", query="unknown", query_type="abstain_expected")
    e1 = QueryEvaluation(
        retrieved_chunk_ids=["c-a", "c-x"],
        answer_text="It is Berlin.",
        cited_source_ids=["chunk-a"],
        supported_claim_count=2,
        latency_ms=100.0,
        input_tokens=10,
        output_tokens=5,
        estimated_cost_usd=0.001,
    )
    e2 = QueryEvaluation(
        retrieved_chunk_ids=["c-y", "c-b"],
        answer_text="Lyon",
        supported_claim_count=1,
        unsupported_claim_count=1,
        latency_ms=200.0,
    )
    e3 = QueryEvaluation(abstained=True)
    return [(q1, e1), (q2, e2), (q3, e3)]


def test_aggregate_metrics_over_mixed_dataset() -> None:
    aggregate = aggregate_metrics(_sample_pairs(), [1])

    assert aggregate["mrr"] == pytest.approx(0.75)
    assert aggregate["recall@1"] == pytest.approx(0.5)
    assert aggregate["precision@1"] == pytest.approx(0.5)
    assert aggregate["hit@1"] == pytest.approx(0.5)
    assert aggregate["supported_claim_ratio"] == pytest.approx(0.75)
    assert aggregate["unsupported_claim_count"] == pytest.approx(1.0)
    assert aggregate["citation_validity"] == pytest.approx(1.0)
    assert aggregate["abstention_accuracy"] == pytest.approx(1.0)
    assert aggregate["abstention_precision"] == pytest.approx(1.0)
    assert aggregate["abstention_recall"] == pytest.approx(1.0)
    assert aggregate["answer_match"] == pytest.approx(0.5)
    assert aggregate["must_cite_satisfied"] == pytest.approx(1.0)
    assert aggregate["latency_ms_p50"] == pytest.approx(150.0)
    assert aggregate["latency_ms_p95"] == pytest.approx(195.0)
    assert aggregate["input_tokens_total"] == pytest.approx(10.0)
    assert aggregate["estimated_cost_usd_total"] == pytest.approx(0.001)


def test_aggregate_abstention_recall_penalizes_missed_abstention() -> None:
    q = GoldenQuery(id="q", query="unknown", query_type="abstain_expected")
    e = QueryEvaluation(answer_text="fabricated", supported_claim_count=1)
    aggregate = aggregate_metrics([(q, e)], [1])

    assert aggregate["abstention_recall"] == pytest.approx(0.0)
    assert aggregate["abstention_accuracy"] == pytest.approx(0.0)


# --- Experiment runner ---


@pytest.mark.anyio
async def test_run_experiment_builds_report() -> None:
    pairs = _sample_pairs()
    evaluations = {query.id: evaluation for query, evaluation in pairs}
    dataset = GoldenDataset(
        metadata=DatasetMetadata(name="sample", version=1, tenant="eval-sample"),
        queries=[query for query, _ in pairs],
    )

    async def evaluator(query: GoldenQuery) -> QueryEvaluation:
        return evaluations[query.id]

    report = await run_experiment(
        dataset=dataset,
        evaluator=evaluator,
        config_name="deterministic",
        created_at="2026-07-14T00:00:00Z",
        k_values=[1],
    )

    assert report.run.query_count == 3
    assert report.run.config_name == "deterministic"
    assert report.run.dataset_name == "sample"
    assert len(report.per_query) == 3
    assert report.aggregate["mrr"] == pytest.approx(0.75)
    assert report.per_query[0].query_id == "q1"


# --- Dataset loader + validation ---


def test_load_dataset_reads_yaml_and_jsonl(tmp_path: Path) -> None:
    (tmp_path / "dataset.yaml").write_text(
        "name: acme-smoke\nversion: 1\ntenant: eval-acme\n", encoding="utf-8"
    )
    lines = [
        {"id": "q1", "query": "Where is Acme?", "query_type": "factoid",
         "expected_answer": "Berlin", "relevant_chunk_ids": ["c-a"]},
        {"id": "q2", "query": "Unknowable?", "query_type": "abstain_expected"},
    ]
    (tmp_path / "queries.jsonl").write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8"
    )

    dataset = load_dataset(tmp_path)

    assert dataset.metadata.name == "acme-smoke"
    assert dataset.metadata.tenant == "eval-acme"
    assert [q.id for q in dataset.queries] == ["q1", "q2"]
    assert dataset.queries[1].expect_abstain is True


def test_golden_query_rejects_expected_answer_when_abstaining() -> None:
    with pytest.raises(ValidationError, match="must not set expected_answer"):
        GoldenQuery(
            id="q",
            query="x",
            query_type="factoid",
            expect_abstain=True,
            expected_answer="nope",
        )


def test_golden_dataset_rejects_duplicate_ids() -> None:
    query = _factoid("dup", ["c-a"], "Berlin")
    with pytest.raises(ValidationError, match="duplicate query id"):
        GoldenDataset(
            metadata=DatasetMetadata(name="d", version=1, tenant="t"),
            queries=[query, query],
        )


# --- Report I/O ---


def test_report_round_trip(tmp_path: Path) -> None:
    pairs = _sample_pairs()
    dataset = GoldenDataset(
        metadata=DatasetMetadata(name="sample", version=2, tenant="t"),
        queries=[q for q, _ in pairs],
    )
    import asyncio

    evaluations = {q.id: e for q, e in pairs}

    async def evaluator(query: GoldenQuery) -> QueryEvaluation:
        return evaluations[query.id]

    report = asyncio.run(
        run_experiment(
            dataset=dataset,
            evaluator=evaluator,
            config_name="deterministic",
            created_at="2026-07-14T00:00:00Z",
            k_values=[1],
        )
    )
    path = tmp_path / "reports" / "sample" / "deterministic.json"
    write_report(report, path)
    restored = read_report(path)

    assert isinstance(restored, ExperimentReport)
    assert restored.run.dataset_version == 2
    assert restored.aggregate["mrr"] == pytest.approx(0.75)
    assert len(restored.per_query) == 3


# --- Baselines / thresholds ---


def test_check_thresholds_flags_min_max_and_missing() -> None:
    aggregate = {"recall@1": 0.5, "unsupported_claim_count": 4.0}
    thresholds = {
        "recall@1": MetricThreshold(min=0.7),
        "unsupported_claim_count": MetricThreshold(max=1.0),
        "answer_match": MetricThreshold(min=0.6),
    }

    violations = check_thresholds(aggregate, thresholds)
    kinds = {v.metric: v.kind for v in violations}

    assert kinds["recall@1"] == "min"
    assert kinds["unsupported_claim_count"] == "max"
    assert kinds["answer_match"] == "missing"


def test_check_thresholds_passes_within_bounds() -> None:
    aggregate = {"recall@1": 0.8}
    assert check_thresholds(aggregate, {"recall@1": MetricThreshold(min=0.7)}) == []


def test_check_regressions_respects_metric_direction() -> None:
    aggregate = {"recall@1": 0.5, "unsupported_claim_count": 3.0, "hit@1": 0.9}
    baseline = {"recall@1": 0.8, "unsupported_claim_count": 1.0, "hit@1": 0.9}

    violations = check_regressions(aggregate, baseline, tolerance=0.05)
    regressed = {v.metric for v in violations}

    assert "recall@1" in regressed  # higher-is-better dropped
    assert "unsupported_claim_count" in regressed  # lower-is-better rose
    assert "hit@1" not in regressed  # unchanged


def test_baseline_round_trip(tmp_path: Path) -> None:
    aggregate = {"recall@1": 0.5, "mrr": 0.75}
    path = tmp_path / "baselines.json"
    save_baseline(path, aggregate)

    assert load_baseline(path) == aggregate
