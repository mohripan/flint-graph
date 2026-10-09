from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.query_runs import get_query_run
from flint_graph.infrastructure.db.models import QueryRunCandidate, QueryRunLinkedEntity


async def inspect_query_retrieval(
    session: AsyncSession, *, tenant_id: UUID, query_run_id: UUID
) -> dict[str, Any]:
    await get_query_run(session, tenant_id=tenant_id, query_run_id=query_run_id)
    rows = await session.scalars(
        select(QueryRunCandidate)
        .where(
            QueryRunCandidate.tenant_id == tenant_id,
            QueryRunCandidate.query_run_id == query_run_id,
        )
        .order_by(QueryRunCandidate.source, QueryRunCandidate.rank, QueryRunCandidate.dedupe_key)
    )
    links = await session.scalars(
        select(QueryRunLinkedEntity)
        .where(
            QueryRunLinkedEntity.tenant_id == tenant_id,
            QueryRunLinkedEntity.query_run_id == query_run_id,
            QueryRunLinkedEntity.canonical_entity_id.is_not(None),
        )
        .order_by(QueryRunLinkedEntity.score.desc(), QueryRunLinkedEntity.canonical_entity_id)
    )
    return {
        "query_run_id": query_run_id,
        "candidates": [
            {
                "candidate_id": row.dedupe_key,
                "source": row.source,
                "candidate_type": row.candidate_type,
                "source_ids": row.source_ids,
                "rank": row.rank,
                "raw_score": row.raw_score,
                "normalized_score": row.normalized_score,
                "fusion_score": row.fusion_score,
                "rerank_score": row.rerank_score,
                "rerank_rank": row.rerank_rank,
                **{
                    key: row.metadata_.get(key)
                    for key in (
                        "document_id", "document_version_id",
                        "subject_entity_id", "object_entity_id",
                    )
                },
            }
            for row in rows
        ],
        # Linking is not retrieval. Callers must not silently score these as graph hits.
        "linked_entity_ids": list(dict.fromkeys(str(link.canonical_entity_id) for link in links)),
    }
