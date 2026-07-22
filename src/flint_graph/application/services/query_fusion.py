from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.query_orchestration import (
    CandidateType,
    DeterministicQueryReranker,
    QueryCandidate,
    QueryClassification,
    QueryReranker,
    QueryRerankRequest,
    RetrieverSource,
)
from flint_graph.application.services.query_runs import append_query_run_event, get_query_run
from flint_graph.infrastructure.db.models import QueryRunCandidate


@dataclass(frozen=True, slots=True)
class QueryFusionResult:
    input_candidate_count: int
    fused_candidate_count: int


@dataclass(frozen=True, slots=True)
class QueryRerankPersistenceResult:
    reranked_candidate_count: int


async def fuse_query_candidates(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
    classification: QueryClassification,
) -> QueryFusionResult:
    rows = list(
        await session.scalars(
            select(QueryRunCandidate)
            .where(
                QueryRunCandidate.tenant_id == tenant_id,
                QueryRunCandidate.query_run_id == query_run_id,
            )
            .order_by(QueryRunCandidate.source, QueryRunCandidate.rank, QueryRunCandidate.id)
        )
    )
    weights = classification.retrieval_plan.retriever_weights
    fused_groups = _fuse_candidate_rows(rows, weights=weights)

    await append_query_run_event(
        session,
        tenant_id=tenant_id,
        query_run_id=query_run_id,
        event_type="fusion.completed",
        payload={
            "algorithm": "weighted-normalized-score-plus-reciprocal-rank",
            "input_candidate_count": len(rows),
            "fused_candidate_count": len(fused_groups),
            "deduplicated_candidate_count": len(rows) - len(fused_groups),
        },
    )

    if not fused_groups:
        return QueryFusionResult(
            input_candidate_count=len(rows),
            fused_candidate_count=0,
        )
    await session.flush()
    return QueryFusionResult(
        input_candidate_count=len(rows),
        fused_candidate_count=len(fused_groups),
    )


async def rerank_fused_query_candidates(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
    reranker: QueryReranker | None = None,
    max_results: int = 20,
) -> QueryRerankPersistenceResult:
    run = await get_query_run(session, tenant_id=tenant_id, query_run_id=query_run_id)
    rows = list(
        await session.scalars(
            select(QueryRunCandidate)
            .where(
                QueryRunCandidate.tenant_id == tenant_id,
                QueryRunCandidate.query_run_id == query_run_id,
            )
            .order_by(QueryRunCandidate.source, QueryRunCandidate.rank, QueryRunCandidate.id)
        )
    )
    fused_groups = _fused_groups_from_scored_rows(rows)
    if not fused_groups:
        await append_query_run_event(
            session,
            tenant_id=tenant_id,
            query_run_id=query_run_id,
            event_type="rerank.completed",
            payload={"candidate_count": 0, "algorithm": "skipped-empty-candidates"},
        )
        return QueryRerankPersistenceResult(reranked_candidate_count=0)
    representatives = [
        _row_to_candidate(group.representative).model_copy(
            update={
                "fusion_score": group.fusion_score,
                "reasons": [
                    *group.representative.reasons,
                    "weighted source fusion",
                ],
            }
        )
        for group in sorted(
            fused_groups,
            key=lambda group: (
                -group.fusion_score,
                -group.representative.normalized_score,
                group.representative.dedupe_key,
            ),
        )
    ]
    result_limit = min(max_results, len(representatives))
    rerank_model = reranker or DeterministicQueryReranker()
    rerank_result = await rerank_model.rerank(
        QueryRerankRequest(
            query=run.query_text,
            candidates=representatives,
            max_results=result_limit,
        )
    )
    ranked_by_candidate_id = {
        candidate.candidate_id: candidate for candidate in rerank_result.candidates
    }
    for row in rows:
        ranked = ranked_by_candidate_id.get(row.dedupe_key)
        if ranked is None:
            row.rerank_score = None
            row.rerank_rank = None
            continue
        row.rerank_score = ranked.rerank_score
        row.rerank_rank = ranked.rerank_rank
        row.reasons = list(ranked.reasons)

    await append_query_run_event(
        session,
        tenant_id=tenant_id,
        query_run_id=query_run_id,
        event_type="rerank.completed",
        payload={
            "candidate_count": len(rerank_result.candidates),
            "algorithm": rerank_result.metadata.get("algorithm", "unknown"),
        },
    )
    await session.flush()
    return QueryRerankPersistenceResult(
        reranked_candidate_count=len(rerank_result.candidates),
    )


@dataclass(frozen=True, slots=True)
class _FusedCandidateGroup:
    fusion_score: float
    representative: QueryRunCandidate


def _fuse_candidate_rows(
    rows: list[QueryRunCandidate],
    *,
    weights: dict[RetrieverSource, float],
) -> list[_FusedCandidateGroup]:
    grouped: dict[str, list[tuple[float, QueryRunCandidate]]] = {}
    for row in rows:
        source = cast(RetrieverSource, row.source)
        weight = weights.get(source, 0.0)
        contribution = weight * ((row.normalized_score + (1.0 / row.rank)) / 2.0)
        grouped.setdefault(_stable_candidate_key(row), []).append((contribution, row))

    fused: list[_FusedCandidateGroup] = []
    for contributions in grouped.values():
        fusion_score = sum(contribution for contribution, _row in contributions)
        representative = max(
            contributions,
            key=lambda item: (
                item[0],
                item[1].normalized_score,
                -item[1].rank,
                item[1].dedupe_key,
            ),
        )[1]
        for _contribution, row in contributions:
            row.fusion_score = fusion_score
        fused.append(
            _FusedCandidateGroup(
                fusion_score=fusion_score,
                representative=representative,
            )
        )
    return fused


def _fused_groups_from_scored_rows(rows: list[QueryRunCandidate]) -> list[_FusedCandidateGroup]:
    grouped: dict[str, list[QueryRunCandidate]] = {}
    for row in rows:
        if row.fusion_score is None:
            continue
        grouped.setdefault(_stable_candidate_key(row), []).append(row)

    fused: list[_FusedCandidateGroup] = []
    for group_rows in grouped.values():
        representative = max(
            group_rows,
            key=lambda row: (
                row.fusion_score or 0.0,
                -row.rank,
                row.normalized_score,
                row.dedupe_key,
            ),
        )
        fused.append(
            _FusedCandidateGroup(
                fusion_score=representative.fusion_score or 0.0,
                representative=representative,
            )
        )
    return fused


def _stable_candidate_key(row: QueryRunCandidate) -> str:
    encoded_source_ids = json.dumps(
        row.source_ids,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{row.candidate_type}:{encoded_source_ids}"


def _row_to_candidate(row: QueryRunCandidate) -> QueryCandidate:
    return QueryCandidate(
        candidate_id=row.dedupe_key,
        source=cast(RetrieverSource, row.source),
        candidate_type=cast(CandidateType, row.candidate_type),
        tenant_id=row.tenant_id,
        retrieval_index_version_id=row.retrieval_index_version_id,
        source_ids=dict(row.source_ids),
        text_preview=row.text_preview,
        raw_score=row.raw_score,
        normalized_score=row.normalized_score,
        rank=row.rank,
        fusion_score=row.fusion_score,
        rerank_score=row.rerank_score,
        rerank_rank=row.rerank_rank,
        reasons=list(row.reasons),
        metadata=dict(row.metadata_),
    )
