"""Provider-neutral evaluation metrics.

``QueryEvaluation`` is the abstract "system under test" output for one query — whatever
produced it (the real orchestration pipeline, or a fake in tests). Metrics are pure
functions of a ``GoldenQuery`` and its ``QueryEvaluation``, so the whole module runs
offline and deterministically.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from atlas_rag.evaluation.datasets import GoldenQuery

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")


class QueryEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    retrieved_entity_ids: list[str] = Field(default_factory=list)
    answer_text: str = ""
    abstained: bool = False
    cited_source_ids: list[str] = Field(default_factory=list)
    supported_claim_count: int = Field(default=0, ge=0)
    partial_claim_count: int = Field(default=0, ge=0)
    unsupported_claim_count: int = Field(default=0, ge=0)
    invalid_citation_count: int = Field(default=0, ge=0)
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None


# --- Retrieval metrics (binary relevance) ---


def recall_at_k(relevant: Sequence[str], retrieved: Sequence[str], k: int) -> float:
    relevant_set = set(relevant)
    if not relevant_set:
        return 0.0
    hits = sum(1 for item in retrieved[:k] if item in relevant_set)
    return hits / len(relevant_set)


def precision_at_k(relevant: Sequence[str], retrieved: Sequence[str], k: int) -> float:
    if k <= 0:
        return 0.0
    relevant_set = set(relevant)
    hits = sum(1 for item in retrieved[:k] if item in relevant_set)
    return hits / k


def hit_at_k(relevant: Sequence[str], retrieved: Sequence[str], k: int) -> float:
    relevant_set = set(relevant)
    return 1.0 if any(item in relevant_set for item in retrieved[:k]) else 0.0


def reciprocal_rank(relevant: Sequence[str], retrieved: Sequence[str]) -> float:
    relevant_set = set(relevant)
    for index, item in enumerate(retrieved, start=1):
        if item in relevant_set:
            return 1.0 / index
    return 0.0


def ndcg_at_k(relevant: Sequence[str], retrieved: Sequence[str], k: int) -> float:
    relevant_set = set(relevant)
    dcg = sum(
        1.0 / math.log2(index + 1)
        for index, item in enumerate(retrieved[:k], start=1)
        if item in relevant_set
    )
    ideal_hits = min(len(relevant_set), k)
    idcg = sum(1.0 / math.log2(index + 1) for index in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0


# --- Answer correctness ---


def normalize_answer(text: str) -> str:
    collapsed = _PUNCT_RE.sub(" ", text.casefold())
    return _WHITESPACE_RE.sub(" ", collapsed).strip()


def answer_matches(expected: str, actual: str) -> bool:
    expected_norm = normalize_answer(expected)
    actual_norm = normalize_answer(actual)
    if not expected_norm:
        return False
    return expected_norm == actual_norm or expected_norm in actual_norm


# --- Per-query / aggregate ---


def _retrieval_targets(
    query: GoldenQuery, evaluation: QueryEvaluation
) -> tuple[list[str], list[str]]:
    if query.query_type == "entity":
        return query.relevant_entity_ids, evaluation.retrieved_entity_ids
    return query.relevant_chunk_ids, evaluation.retrieved_chunk_ids


def per_query_metrics(
    query: GoldenQuery, evaluation: QueryEvaluation, k_values: Sequence[int]
) -> dict[str, float]:
    metrics: dict[str, float] = {}
    metrics["abstention_correct"] = 1.0 if evaluation.abstained == query.expect_abstain else 0.0

    relevant, retrieved = _retrieval_targets(query, evaluation)
    if relevant:
        metrics["mrr"] = reciprocal_rank(relevant, retrieved)
        for k in k_values:
            metrics[f"recall@{k}"] = recall_at_k(relevant, retrieved, k)
            metrics[f"precision@{k}"] = precision_at_k(relevant, retrieved, k)
            metrics[f"ndcg@{k}"] = ndcg_at_k(relevant, retrieved, k)
            metrics[f"hit@{k}"] = hit_at_k(relevant, retrieved, k)

    if not evaluation.abstained:
        total_claims = (
            evaluation.supported_claim_count
            + evaluation.partial_claim_count
            + evaluation.unsupported_claim_count
        )
        if total_claims > 0:
            metrics["supported_claim_ratio"] = evaluation.supported_claim_count / total_claims
        metrics["unsupported_claim_count"] = float(evaluation.unsupported_claim_count)
        metrics["citation_valid"] = 1.0 if evaluation.invalid_citation_count == 0 else 0.0

    if not query.expect_abstain and query.expected_answer is not None:
        metrics["answer_match"] = (
            1.0 if answer_matches(query.expected_answer, evaluation.answer_text) else 0.0
        )

    if query.must_cite_sources:
        cited = set(evaluation.cited_source_ids)
        metrics["must_cite_satisfied"] = (
            1.0 if all(source in cited for source in query.must_cite_sources) else 0.0
        )

    return metrics


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[int(rank)]
    frac = rank - low
    return ordered[low] * (1 - frac) + ordered[high] * frac


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def aggregate_metrics(
    pairs: Sequence[tuple[GoldenQuery, QueryEvaluation]], k_values: Sequence[int]
) -> dict[str, float]:
    aggregate: dict[str, float] = {}

    # Retrieval — mean over queries that carry relevance labels.
    labeled = [(q, e, *_retrieval_targets(q, e)) for q, e in pairs]
    labeled = [(q, e, rel, ret) for q, e, rel, ret in labeled if rel]
    if labeled:
        aggregate["mrr"] = _mean([reciprocal_rank(rel, ret) for _, _, rel, ret in labeled])
        for k in k_values:
            aggregate[f"recall@{k}"] = _mean(
                [recall_at_k(rel, ret, k) for _, _, rel, ret in labeled]
            )
            aggregate[f"precision@{k}"] = _mean(
                [precision_at_k(rel, ret, k) for _, _, rel, ret in labeled]
            )
            aggregate[f"ndcg@{k}"] = _mean(
                [ndcg_at_k(rel, ret, k) for _, _, rel, ret in labeled]
            )
            aggregate[f"hit@{k}"] = _mean(
                [hit_at_k(rel, ret, k) for _, _, rel, ret in labeled]
            )

    # Faithfulness — micro-averaged over non-abstained answers.
    answered = [e for _, e in pairs if not e.abstained]
    if answered:
        total_supported = sum(e.supported_claim_count for e in answered)
        total_claims = sum(
            e.supported_claim_count + e.partial_claim_count + e.unsupported_claim_count
            for e in answered
        )
        if total_claims > 0:
            aggregate["supported_claim_ratio"] = total_supported / total_claims
        aggregate["unsupported_claim_count"] = float(
            sum(e.unsupported_claim_count for e in answered)
        )
        aggregate["citation_validity"] = _mean(
            [1.0 if e.invalid_citation_count == 0 else 0.0 for e in answered]
        )

    # Abstention — confusion matrix over expect_abstain vs abstained.
    tp = sum(1 for q, e in pairs if q.expect_abstain and e.abstained)
    fp = sum(1 for q, e in pairs if not q.expect_abstain and e.abstained)
    fn = sum(1 for q, e in pairs if q.expect_abstain and not e.abstained)
    if pairs:
        tn = len(pairs) - tp - fp - fn
        aggregate["abstention_accuracy"] = (tp + tn) / len(pairs)
    if tp + fp > 0:
        aggregate["abstention_precision"] = tp / (tp + fp)
    if tp + fn > 0:
        aggregate["abstention_recall"] = tp / (tp + fn)

    # Answer correctness — over answerable queries with a reference answer.
    answerable = [
        (q, e)
        for q, e in pairs
        if not q.expect_abstain and q.expected_answer is not None
    ]
    if answerable:
        aggregate["answer_match"] = _mean(
            [
                1.0 if answer_matches(q.expected_answer or "", e.answer_text) else 0.0
                for q, e in answerable
            ]
        )

    must_cite = [(q, e) for q, e in pairs if q.must_cite_sources]
    if must_cite:
        aggregate["must_cite_satisfied"] = _mean(
            [
                1.0 if set(q.must_cite_sources) <= set(e.cited_source_ids) else 0.0
                for q, e in must_cite
            ]
        )

    # Operational.
    latencies = [e.latency_ms for _, e in pairs if e.latency_ms is not None]
    if latencies:
        aggregate["latency_ms_p50"] = _percentile(latencies, 50)
        aggregate["latency_ms_p95"] = _percentile(latencies, 95)
    aggregate["input_tokens_total"] = float(
        sum(e.input_tokens or 0 for _, e in pairs)
    )
    aggregate["output_tokens_total"] = float(
        sum(e.output_tokens or 0 for _, e in pairs)
    )
    aggregate["estimated_cost_usd_total"] = sum(
        e.estimated_cost_usd or 0.0 for _, e in pairs
    )

    return aggregate
