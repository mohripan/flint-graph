from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.query_orchestration import (
    PackedContextRecord,
    QueryContextPack,
)
from atlas_rag.application.services.query_runs import (
    append_query_run_event,
    persist_query_context_pack,
)
from atlas_rag.infrastructure.db.models import QueryRunCandidate


@dataclass(frozen=True, slots=True)
class QueryContextPackingResult:
    pack_id: str
    record_count: int
    token_count: int
    skipped_candidate_count: int


async def pack_query_context(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
    token_budget: int,
    max_records: int,
) -> QueryContextPackingResult:
    rows = list(
        await session.scalars(
            select(QueryRunCandidate)
            .where(
                QueryRunCandidate.tenant_id == tenant_id,
                QueryRunCandidate.query_run_id == query_run_id,
                QueryRunCandidate.rerank_rank.is_not(None),
            )
            .order_by(
                QueryRunCandidate.rerank_rank,
                QueryRunCandidate.fusion_score.desc().nullslast(),
                QueryRunCandidate.rank,
                QueryRunCandidate.id,
            )
        )
    )

    records: list[PackedContextRecord] = []
    token_count = 0
    skipped_count = 0
    for row in rows:
        text = (row.text_preview or "").strip()
        candidate_tokens = _estimate_token_count(text)
        if not text or candidate_tokens <= 0:
            skipped_count += 1
            continue
        if len(records) >= max_records:
            skipped_count += 1
            continue
        if token_count + candidate_tokens > token_budget:
            skipped_count += 1
            continue

        record_number = len(records) + 1
        records.append(
            PackedContextRecord(
                context_id=f"ctx-{record_number:04d}",
                candidate_id=row.dedupe_key,
                citation_id=f"c{record_number}",
                text=text,
                token_count=candidate_tokens,
                source_ids=dict(row.source_ids),
                metadata={
                    "source": row.source,
                    "candidate_type": row.candidate_type,
                    "rank": row.rank,
                    "fusion_score": row.fusion_score,
                    "rerank_score": row.rerank_score,
                    "rerank_rank": row.rerank_rank,
                },
            )
        )
        token_count += candidate_tokens

    pack_id = f"query-pack-{query_run_id}"
    await persist_query_context_pack(
        session,
        tenant_id=tenant_id,
        query_run_id=query_run_id,
        context_pack=QueryContextPack(
            pack_id=pack_id,
            pack_version=1,
            token_budget=token_budget,
            records=records,
            metadata={
                "algorithm": "rerank-order-preview-packer",
                "max_records": max_records,
                "skipped_candidate_count": skipped_count,
            },
        ),
    )
    await append_query_run_event(
        session,
        tenant_id=tenant_id,
        query_run_id=query_run_id,
        event_type="context.packed",
        payload={
            "pack_id": pack_id,
            "pack_version": 1,
            "record_count": len(records),
            "token_budget": token_budget,
            "token_count": token_count,
            "skipped_candidate_count": skipped_count,
        },
    )
    await session.flush()
    return QueryContextPackingResult(
        pack_id=pack_id,
        record_count=len(records),
        token_count=token_count,
        skipped_candidate_count=skipped_count,
    )


def _estimate_token_count(text: str) -> int:
    return len(text.split())
