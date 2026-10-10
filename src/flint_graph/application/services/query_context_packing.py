from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.query_orchestration import (
    PackedContextRecord,
    QueryContextPack,
)
from flint_graph.application.services.query_runs import (
    append_query_run_event,
    persist_query_context_pack,
)
from flint_graph.domain.enums import DocumentVersionStatus, RelationshipStatus
from flint_graph.infrastructure.db.models import (
    Document,
    DocumentChunk,
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
    skipped_reasons: dict[str, int] = {}
    chunk_evidence = await _load_chunk_evidence(session, tenant_id=tenant_id, rows=rows)
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
            _count_skip(skipped_reasons, "inactive_source")
            continue
        evidence = _candidate_evidence(row, chunks=chunk_evidence)
        if evidence is None:
            skipped_count += 1
            _count_skip(skipped_reasons, "missing_or_stale_chunk")
            continue
        text, source_ids, evidence_metadata = evidence
        if len(text) > 4000:
            skipped_count += 1
            _count_skip(skipped_reasons, "record_character_limit")
            continue
        candidate_tokens = _estimate_token_count(text)
        if not text.strip() or candidate_tokens <= 0:
            skipped_count += 1
            _count_skip(skipped_reasons, "empty_record")
            continue
        if len(records) >= max_records:
            skipped_count += 1
            _count_skip(skipped_reasons, "record_limit")
            continue
        if token_count + candidate_tokens > token_budget:
            skipped_count += 1
            _count_skip(skipped_reasons, "token_budget")
            continue

        record_number = len(records) + 1
        records.append(
            PackedContextRecord(
                context_id=f"ctx-{record_number:04d}",
                candidate_id=row.dedupe_key,
                citation_id=f"c{record_number}",
                text=text,
                token_count=candidate_tokens,
                source_ids=source_ids,
                metadata={
                    **dict(row.metadata_),
                    "source": row.source,
                    "candidate_type": row.candidate_type,
                    "rank": row.rank,
                    "fusion_score": row.fusion_score,
                    "rerank_score": row.rerank_score,
                    "rerank_rank": row.rerank_rank,
                    **evidence_metadata,
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
                "algorithm": "rerank-order-authoritative-chunk-packer-v2",
                "max_records": max_records,
                "skipped_candidate_count": skipped_count,
                "skipped_candidate_reasons": skipped_reasons,
                "token_estimator": "whitespace-words-not-model-tokens",
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
            "skipped_candidate_reasons": skipped_reasons,
        },
    )
    await session.flush()
    return QueryContextPackingResult(
        pack_id=pack_id,
        record_count=len(records),
        token_count=token_count,
        skipped_candidate_count=skipped_count,
    )


def _count_skip(reasons: dict[str, int], reason: str) -> None:
    reasons[reason] = reasons.get(reason, 0) + 1


async def _load_chunk_evidence(
    session: AsyncSession, *, tenant_id: UUID, rows: list[QueryRunCandidate]
) -> dict[tuple[UUID, str], DocumentChunk]:
    keys = {
        (version_id, row.source_ids["chunk_id"])
        for row in rows
        if row.candidate_type == "chunk"
        and (version_id := _candidate_document_version_id(row)) is not None
        and row.source_ids.get("chunk_id")
    }
    if not keys:
        return {}
    chunks = await session.scalars(
        select(DocumentChunk)
        .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            DocumentChunk.tenant_id == tenant_id,
            Document.tenant_id == tenant_id,
            Document.deleted_at.is_(None),
            DocumentVersion.status == DocumentVersionStatus.ACTIVE,
            DocumentChunk.document_id == Document.id,
            tuple_(DocumentChunk.document_version_id, DocumentChunk.chunk_id).in_(keys),
        )
    )
    return {(chunk.document_version_id, chunk.chunk_id): chunk for chunk in chunks}


def _candidate_evidence(
    row: QueryRunCandidate, *, chunks: dict[tuple[UUID, str], DocumentChunk]
) -> tuple[str, dict[str, str], dict[str, object]] | None:
    version_id = _candidate_document_version_id(row)
    if row.candidate_type != "chunk" or version_id is None:
        # Internal legacy fixtures/adapters may not have immutable chunk identities.
        # Public chunk retrievers always provide them. Never call this full evidence.
        if row.candidate_type == "chunk" and (
            "document_version_id" in row.source_ids or "document_version_id" in row.metadata_
        ):
            return None
        return (row.text_preview or "", dict(row.source_ids), {"evidence_origin": "legacy_preview"})
    chunk = chunks.get((version_id, row.source_ids.get("chunk_id", "")))
    if chunk is None or row.metadata_.get("chunk_hash") != chunk.chunk_hash:
        return None
    # Reject contradictory identities in either projection reference field.
    for mapping in (row.source_ids, row.metadata_):
        if (mapping.get("document_id") not in (None, str(chunk.document_id))
                or mapping.get("document_version_id") not in (None, str(version_id))):
            return None
    return (
        chunk.text,
        {**row.source_ids, "document_id": str(chunk.document_id),
         "document_version_id": str(version_id), "chunk_id": chunk.chunk_id},
        {"evidence_origin": "postgresql_chunk", "document_id": str(chunk.document_id),
         "document_version_id": str(version_id), "chunk_hash": chunk.chunk_hash,
         "heading_path": chunk.heading_path, "page_start": chunk.page_start,
         "page_end": chunk.page_end, "source_element_ids": chunk.source_element_ids,
         "source_offsets": chunk.source_offsets},
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
    value = row.source_ids.get("document_version_id", row.metadata_.get("document_version_id"))
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
