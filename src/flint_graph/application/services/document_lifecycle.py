from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.graph_projection import reconcile_tenant_graph
from flint_graph.application.services.lexical_projection import LexicalChunkRecord
from flint_graph.application.services.vector_projection import (
    SupportsCypher,
    VectorChunkRecord,
    delete_chunk_vectors,
    vector_chunk_node_id,
)
from flint_graph.domain.enums import (
    DocumentIndexCoverageStatus,
    DocumentLifecycleEventType,
    DocumentProjectionCleanupStatus,
    DocumentVersionStatus,
    MentionResolutionStatus,
    RelationshipStatus,
)
from flint_graph.domain.errors import ConflictError, NotFoundError
from flint_graph.infrastructure.db.models import (
    CanonicalEntity,
    Document,
    DocumentChunk,
    DocumentIndexCoverage,
    DocumentLifecycleEvent,
    DocumentProjectionCleanup,
    DocumentVersion,
    EntityMention,
    EntityRelationship,
    RetrievalIndexVersion,
)
from flint_graph.infrastructure.opensearch import build_delete_chunks_bulk_body
from flint_graph.observability import metrics
from flint_graph.observability.instruments import PROJECTION_CLEANUP_BACKLOG


class SupportsOpenSearchBulk(Protocol):
    async def bulk(self, *, body: str) -> None: ...


@dataclass(frozen=True, slots=True)
class DeleteDocumentResult:
    document_id: UUID
    deleted_version_ids: list[UUID]
    cleanup_count: int


async def delete_document(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    reason: str | None = None,
) -> DeleteDocumentResult:
    document = await session.scalar(
        select(Document)
        .where(Document.id == document_id, Document.tenant_id == tenant_id)
        .with_for_update()
    )
    if document is None:
        raise NotFoundError(f"Document '{document_id}' was not found.")
    if document.deleted_at is None:
        document.deleted_at = datetime.now(UTC)

    versions = list(
        await session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number)
            .with_for_update()
        )
    )
    mutable_statuses = {
        DocumentVersionStatus.PENDING,
        DocumentVersionStatus.ACTIVE,
        DocumentVersionStatus.SUPERSEDED,
    }
    deleted_versions: list[DocumentVersion] = []
    for version in versions:
        if version.status in mutable_statuses:
            version.status = DocumentVersionStatus.DELETED
            deleted_versions.append(version)

    deleted_version_ids = [version.id for version in deleted_versions]
    if deleted_version_ids:
        running_coverages = list(
            await session.scalars(
                select(DocumentIndexCoverage)
                .where(
                    DocumentIndexCoverage.tenant_id == tenant_id,
                    DocumentIndexCoverage.document_version_id.in_(deleted_version_ids),
                    DocumentIndexCoverage.status == DocumentIndexCoverageStatus.RUNNING,
                )
                .with_for_update()
            )
        )
        for coverage in running_coverages:
            coverage.status = DocumentIndexCoverageStatus.CANCELLED
            coverage.error_code = "document_deleted"
            coverage.error_message = "Document was deleted before indexing completed."

    event = DocumentLifecycleEvent(
        tenant_id=tenant_id,
        document_id=document.id,
        document_version_id=None,
        event_type=DocumentLifecycleEventType.DOCUMENT_DELETED,
        reason=reason,
        payload={"deleted_version_ids": [str(version_id) for version_id in deleted_version_ids]},
    )
    session.add(event)

    cleanup_count = 0
    for version in versions:
        cleanup_count += await create_projection_cleanup_records_for_version(
            session,
            tenant_id=tenant_id,
            document_id=document.id,
            document_version_id=version.id,
            stale_reason="document_deleted",
        )

    await session.flush()
    return DeleteDocumentResult(
        document_id=document.id,
        deleted_version_ids=deleted_version_ids,
        cleanup_count=cleanup_count,
    )


async def record_superseded_version_cleanup(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    superseded_versions: list[DocumentVersion],
) -> int:
    cleanup_count = 0
    for version in superseded_versions:
        session.add(
            DocumentLifecycleEvent(
                tenant_id=tenant_id,
                document_id=version.document_id,
                document_version_id=version.id,
                event_type=DocumentLifecycleEventType.VERSION_SUPERSEDED,
                reason="new version activated",
                payload={"version_number": version.version_number},
            )
        )
        cleanup_count += await create_projection_cleanup_records_for_version(
            session,
            tenant_id=tenant_id,
            document_id=version.document_id,
            document_version_id=version.id,
            stale_reason="version_superseded",
        )
    await session.flush()
    return cleanup_count


async def create_projection_cleanup_records_for_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    document_version_id: UUID,
    stale_reason: str,
) -> int:
    coverages = list(
        await session.scalars(
            select(DocumentIndexCoverage).where(
                DocumentIndexCoverage.tenant_id == tenant_id,
                DocumentIndexCoverage.document_id == document_id,
                DocumentIndexCoverage.document_version_id == document_version_id,
                DocumentIndexCoverage.status == DocumentIndexCoverageStatus.COMPLETED,
            )
        )
    )
    created = 0
    for coverage in coverages:
        existing = await session.scalar(
            select(DocumentProjectionCleanup).where(
                DocumentProjectionCleanup.document_version_id == document_version_id,
                DocumentProjectionCleanup.retrieval_index_version_id
                == coverage.retrieval_index_version_id,
                DocumentProjectionCleanup.stale_reason == stale_reason,
            )
        )
        if existing is not None:
            continue
        session.add(
            DocumentProjectionCleanup(
                tenant_id=tenant_id,
                document_id=document_id,
                document_version_id=document_version_id,
                retrieval_index_version_id=coverage.retrieval_index_version_id,
                status=DocumentProjectionCleanupStatus.PENDING,
                stale_reason=stale_reason,
                chunk_count=coverage.chunk_count,
                vector_count=coverage.vector_count,
                lexical_count=coverage.lexical_count,
            )
        )
        created += 1
    if created:
        await session.flush()
    return created


async def list_lifecycle_events(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    limit: int = 100,
) -> list[DocumentLifecycleEvent]:
    await _require_document(session, tenant_id=tenant_id, document_id=document_id)
    rows = await session.scalars(
        select(DocumentLifecycleEvent)
        .where(
            DocumentLifecycleEvent.tenant_id == tenant_id,
            DocumentLifecycleEvent.document_id == document_id,
        )
        .order_by(DocumentLifecycleEvent.created_at.desc(), DocumentLifecycleEvent.id.desc())
        .limit(limit)
    )
    return list(rows)


async def list_projection_cleanups(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    limit: int = 100,
) -> list[DocumentProjectionCleanup]:
    await _require_document(session, tenant_id=tenant_id, document_id=document_id)
    rows = await session.scalars(
        select(DocumentProjectionCleanup)
        .where(
            DocumentProjectionCleanup.tenant_id == tenant_id,
            DocumentProjectionCleanup.document_id == document_id,
        )
        .order_by(DocumentProjectionCleanup.created_at.desc(), DocumentProjectionCleanup.id.desc())
        .limit(limit)
    )
    return list(rows)


async def retry_projection_cleanups(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
) -> list[DocumentProjectionCleanup]:
    await _require_document(session, tenant_id=tenant_id, document_id=document_id)
    cleanups = list(
        await session.scalars(
            select(DocumentProjectionCleanup)
            .where(
                DocumentProjectionCleanup.tenant_id == tenant_id,
                DocumentProjectionCleanup.document_id == document_id,
                DocumentProjectionCleanup.status.in_(
                    [
                        DocumentProjectionCleanupStatus.FAILED,
                        DocumentProjectionCleanupStatus.PENDING,
                    ]
                ),
            )
            .with_for_update()
        )
    )
    for cleanup in cleanups:
        cleanup.status = DocumentProjectionCleanupStatus.PENDING
        cleanup.error_code = None
        cleanup.error_message = None
        cleanup.completed_at = None
    session.add(
        DocumentLifecycleEvent(
            tenant_id=tenant_id,
            document_id=document_id,
            document_version_id=None,
            event_type=DocumentLifecycleEventType.CLEANUP_RETRIED,
            reason="projection cleanup retry requested",
            payload={"cleanup_ids": [str(cleanup.id) for cleanup in cleanups]},
        )
    )
    await session.flush()
    return cleanups


async def run_next_projection_cleanup(
    session: AsyncSession,
    *,
    neo4j_client: SupportsCypher,
    opensearch_client: SupportsOpenSearchBulk,
) -> DocumentProjectionCleanup | None:
    cleanup = await session.scalar(
        select(DocumentProjectionCleanup)
        .where(DocumentProjectionCleanup.status == DocumentProjectionCleanupStatus.PENDING)
        .order_by(DocumentProjectionCleanup.created_at, DocumentProjectionCleanup.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if cleanup is None:
        await record_projection_cleanup_backlog(session)
        return None
    result = await run_projection_cleanup(
        session,
        cleanup_id=cleanup.id,
        neo4j_client=neo4j_client,
        opensearch_client=opensearch_client,
    )
    await record_projection_cleanup_backlog(session)
    return result


async def record_projection_cleanup_backlog(session: AsyncSession) -> dict[str, int]:
    """Publish the cleanup backlog gauge, by status.

    A projection cleanup that never drains means deleted content stays queryable,
    so the backlog is a correctness signal, not just a queue depth.
    """
    rows = await session.execute(
        select(
            DocumentProjectionCleanup.status,
            func.count(DocumentProjectionCleanup.id),
        )
        .where(
            DocumentProjectionCleanup.status.in_(
                [
                    DocumentProjectionCleanupStatus.PENDING,
                    DocumentProjectionCleanupStatus.RUNNING,
                    DocumentProjectionCleanupStatus.FAILED,
                ]
            )
        )
        .group_by(DocumentProjectionCleanup.status)
    )
    counts = {status.value: 0 for status in DocumentProjectionCleanupStatus}
    for status, count in rows.all():
        counts[status.value] = int(count)
    for status_value, count in counts.items():
        if status_value in {"pending", "running", "failed"}:
            metrics.set_gauge(
                PROJECTION_CLEANUP_BACKLOG,
                count,
                **{"flint_graph.cleanup.status": status_value},
            )
    return counts


async def run_projection_cleanup(
    session: AsyncSession,
    *,
    cleanup_id: UUID,
    neo4j_client: SupportsCypher,
    opensearch_client: SupportsOpenSearchBulk,
) -> DocumentProjectionCleanup:
    cleanup = await session.scalar(
        select(DocumentProjectionCleanup)
        .where(DocumentProjectionCleanup.id == cleanup_id)
        .with_for_update()
    )
    if cleanup is None:
        raise NotFoundError(f"Projection cleanup '{cleanup_id}' was not found.")
    if cleanup.status == DocumentProjectionCleanupStatus.COMPLETED:
        return cleanup
    if cleanup.status == DocumentProjectionCleanupStatus.RUNNING:
        raise ConflictError(f"Projection cleanup '{cleanup_id}' is already running.")

    cleanup.status = DocumentProjectionCleanupStatus.RUNNING
    cleanup.attempt_count += 1
    cleanup.started_at = datetime.now(UTC)
    cleanup.completed_at = None
    cleanup.error_code = None
    cleanup.error_message = None
    await session.flush()

    try:
        index_version = await _load_index_version(
            session,
            cleanup.retrieval_index_version_id,
        )
        document = await _require_document(
            session,
            tenant_id=cleanup.tenant_id,
            document_id=cleanup.document_id,
        )
        chunks = list(
            await session.scalars(
                select(DocumentChunk)
                .where(
                    DocumentChunk.tenant_id == cleanup.tenant_id,
                    DocumentChunk.document_id == cleanup.document_id,
                    DocumentChunk.document_version_id == cleanup.document_version_id,
                )
                .order_by(DocumentChunk.chunk_index)
            )
        )
        lexical_records = [
            LexicalChunkRecord(
                tenant_id=chunk.tenant_id,
                document_id=chunk.document_id,
                document_version_id=chunk.document_version_id,
                chunk_id=chunk.chunk_id,
                chunk_hash=chunk.chunk_hash,
                title=document.title,
                text=chunk.text,
                heading_path=chunk.heading_path,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                source_uri=document.source_uri,
                metadata=chunk.metadata_,
                active=False,
            )
            for chunk in chunks
        ]
        chunk_node_ids = [
            vector_chunk_node_id(
                VectorChunkRecord(
                    tenant_id=chunk.tenant_id,
                    document_id=chunk.document_id,
                    document_version_id=chunk.document_version_id,
                    chunk_id=chunk.chunk_id,
                    chunk_hash=chunk.chunk_hash,
                    retrieval_index_version_id=cleanup.retrieval_index_version_id,
                    vector=[],
                )
            )
            for chunk in chunks
        ]

        if chunk_node_ids:
            await delete_chunk_vectors(
                neo4j_client,
                tenant_id=cleanup.tenant_id,
                retrieval_index_version_id=cleanup.retrieval_index_version_id,
                chunk_node_ids=chunk_node_ids,
            )
        if lexical_records:
            await opensearch_client.bulk(
                body=build_delete_chunks_bulk_body(
                    index_name=index_version.opensearch_index_name,
                    records=lexical_records,
                )
            )
        await _invalidate_graph_support_for_version(
            session,
            tenant_id=cleanup.tenant_id,
            document_version_id=cleanup.document_version_id,
        )
        await reconcile_tenant_graph(
            session,
            client=neo4j_client,
            tenant_id=cleanup.tenant_id,
        )
    except Exception as exc:
        cleanup.status = DocumentProjectionCleanupStatus.FAILED
        cleanup.error_code = "projection_cleanup_failed"
        cleanup.error_message = str(exc)
        await session.flush()
        return cleanup

    cleanup.status = DocumentProjectionCleanupStatus.COMPLETED
    cleanup.chunk_count = len(chunks)
    cleanup.vector_count = len(chunk_node_ids)
    cleanup.lexical_count = len(lexical_records)
    cleanup.completed_at = datetime.now(UTC)
    await session.flush()
    return cleanup


async def _invalidate_graph_support_for_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_version_id: UUID,
) -> None:
    relationships = list(
        await session.scalars(
            select(EntityRelationship).where(EntityRelationship.tenant_id == tenant_id)
        )
    )
    document_version_text = str(document_version_id)
    for relationship in relationships:
        retained = [
            item
            for item in relationship.provenance
            if str(item.get("document_version_id")) != document_version_text
        ]
        if len(retained) == len(relationship.provenance):
            continue
        relationship.provenance = retained
        relationship.support_count = len(retained)
        if not retained:
            relationship.status = RelationshipStatus.DEPRECATED

    impacted_entity_ids = list(
        await session.scalars(
            select(EntityMention.resolved_entity_id)
            .where(
                EntityMention.tenant_id == tenant_id,
                EntityMention.document_version_id == document_version_id,
                EntityMention.resolved_entity_id.is_not(None),
            )
            .distinct()
        )
    )
    if not impacted_entity_ids:
        return
    active_counts = {
        entity_id: count
        for entity_id, count in (
            await session.execute(
                select(EntityMention.resolved_entity_id, func.count())
                .join(DocumentVersion, DocumentVersion.id == EntityMention.document_version_id)
                .where(
                    EntityMention.tenant_id == tenant_id,
                    EntityMention.resolved_entity_id.in_(impacted_entity_ids),
                    EntityMention.resolution_status == MentionResolutionStatus.RESOLVED,
                    DocumentVersion.status == DocumentVersionStatus.ACTIVE,
                )
                .group_by(EntityMention.resolved_entity_id)
            )
        ).all()
        if entity_id is not None
    }
    entities = list(
        await session.scalars(
            select(CanonicalEntity).where(
                CanonicalEntity.tenant_id == tenant_id,
                CanonicalEntity.id.in_(impacted_entity_ids),
            )
        )
    )
    for entity in entities:
        entity.support_count = int(active_counts.get(entity.id, 0))


async def _require_document(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
) -> Document:
    document = await session.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
    )
    if document is None:
        raise NotFoundError(f"Document '{document_id}' was not found.")
    return document


async def _load_index_version(
    session: AsyncSession,
    retrieval_index_version_id: UUID,
) -> RetrievalIndexVersion:
    index_version = await session.get(RetrievalIndexVersion, retrieval_index_version_id)
    if index_version is None:
        raise NotFoundError(
            f"Retrieval index version '{retrieval_index_version_id}' was not found."
        )
    return index_version
