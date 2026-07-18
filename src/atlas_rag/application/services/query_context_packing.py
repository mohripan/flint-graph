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
from atlas_rag.domain.enums import DocumentVersionStatus, RelationshipStatus
from atlas_rag.infrastructure.db.models import (
    Document,
    DocumentVersion,
    EntityRelationship,
    QueryRunCandidate,
)


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
    active_document_version_ids = await _active_candidate_document_version_ids(
        session,
        tenant_id=tenant_id,
        rows=rows,
    )
    active_relationship_ids = await _active_candidate_relationship_ids(
        session,
        tenant_id=tenant_id,
        rows=rows,
    )
    for row in rows:
        if not _candidate_source_is_active(
            row,
            active_document_version_ids=active_document_version_ids,
            active_relationship_ids=active_relationship_ids,
        ):
            skipped_count += 1
            continue
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
                    **dict(row.metadata_),
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


async def _active_candidate_document_version_ids(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    rows: list[QueryRunCandidate],
) -> set[UUID]:
    version_ids = {
        version_id
        for row in rows
        if (version_id := _candidate_document_version_id(row)) is not None
    }
    if not version_ids:
        return set()
    return await _active_document_version_ids(
        session,
        tenant_id=tenant_id,
        document_version_ids=version_ids,
    )


async def _active_candidate_relationship_ids(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    rows: list[QueryRunCandidate],
) -> set[UUID]:
    relationship_ids = {
        relationship_id
        for row in rows
        if (relationship_id := _candidate_relationship_id(row)) is not None
    }
    if not relationship_ids:
        return set()

    relationships = list(
        await session.scalars(
            select(EntityRelationship).where(
                EntityRelationship.tenant_id == tenant_id,
                EntityRelationship.id.in_(relationship_ids),
                EntityRelationship.status == RelationshipStatus.ACTIVE,
            )
        )
    )
    provenance_version_ids = {
        version_id
        for relationship in relationships
        for item in relationship.provenance
        if (version_id := _provenance_document_version_id(item)) is not None
    }
    active_version_ids = await _active_document_version_ids(
        session,
        tenant_id=tenant_id,
        document_version_ids=provenance_version_ids,
    )
    active_relationship_ids: set[UUID] = set()
    for relationship in relationships:
        relationship_version_ids = {
            version_id
            for item in relationship.provenance
            if (version_id := _provenance_document_version_id(item)) is not None
        }
        if not relationship_version_ids or relationship_version_ids & active_version_ids:
            active_relationship_ids.add(relationship.id)
    return active_relationship_ids


async def _active_document_version_ids(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_version_ids: set[UUID],
) -> set[UUID]:
    if not document_version_ids:
        return set()
    return set(
        await session.scalars(
            select(DocumentVersion.id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
                DocumentVersion.id.in_(document_version_ids),
                DocumentVersion.status == DocumentVersionStatus.ACTIVE,
            )
        )
    )


def _candidate_source_is_active(
    row: QueryRunCandidate,
    *,
    active_document_version_ids: set[UUID],
    active_relationship_ids: set[UUID],
) -> bool:
    relationship_id = _candidate_relationship_id(row)
    if relationship_id is not None:
        return relationship_id in active_relationship_ids
    document_version_id = _candidate_document_version_id(row)
    if document_version_id is None:
        return True
    return document_version_id in active_document_version_ids


def _candidate_relationship_id(row: QueryRunCandidate) -> UUID | None:
    if row.candidate_type != "relationship":
        return None
    value = row.source_ids.get("relationship_id")
    if value is None:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _candidate_document_version_id(row: QueryRunCandidate) -> UUID | None:
    value = row.metadata_.get("document_version_id")
    if value is None:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _provenance_document_version_id(item: dict[str, object]) -> UUID | None:
    value = item.get("document_version_id")
    if value is None:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _estimate_token_count(text: str) -> int:
    return len(text.split())
