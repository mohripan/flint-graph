from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Subquery

from flint_graph.application.services.indexing import select_active_retrieval_index_version
from flint_graph.application.services.retrieval import require_visible_index_version
from flint_graph.domain.enums import (
    DocumentIndexCoverageStatus,
    DocumentVersionStatus,
)
from flint_graph.infrastructure.db.models import (
    Document,
    DocumentIndexCoverage,
    DocumentVersion,
    RetrievalIndexVersion,
)


@dataclass(frozen=True, slots=True)
class SearchReadinessIndexVersion:
    id: UUID
    embedding_provider: str
    embedding_model: str
    vector_dimension: int
    opensearch_index_name: str
    neo4j_vector_index_name: str


@dataclass(frozen=True, slots=True)
class SearchReadinessDocument:
    document_id: UUID
    document_version_id: UUID
    title: str
    version_number: int
    document_version_status: DocumentVersionStatus
    status: str
    coverage_status: DocumentIndexCoverageStatus | None
    chunk_count: int
    embedded_count: int
    vector_count: int
    lexical_count: int
    error_code: str | None
    error_message: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SearchReadinessSummary:
    ready: bool
    reason: str
    active_index_version: SearchReadinessIndexVersion | None
    completed_coverage_count: int
    running_coverage_count: int
    failed_coverage_count: int
    cancelled_coverage_count: int
    documents: list[SearchReadinessDocument]


async def get_search_readiness(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    retrieval_index_version_id: UUID | None = None,
    recent_document_limit: int = 25,
) -> SearchReadinessSummary:
    index_version = await _resolve_readiness_index_version(
        session,
        tenant_id=tenant_id,
        retrieval_index_version_id=retrieval_index_version_id,
    )
    if index_version is None:
        return SearchReadinessSummary(
            ready=False,
            reason="no_active_index",
            active_index_version=None,
            completed_coverage_count=0,
            running_coverage_count=0,
            failed_coverage_count=0,
            cancelled_coverage_count=0,
            documents=[],
        )

    documents = await _load_recent_document_statuses(
        session,
        tenant_id=tenant_id,
        index_version=index_version,
        limit=recent_document_limit,
    )
    counts = await _load_coverage_totals(session, tenant_id=tenant_id, index_version=index_version)
    completed_count = counts[DocumentIndexCoverageStatus.COMPLETED]
    running_count = counts[DocumentIndexCoverageStatus.RUNNING]
    failed_count = counts[DocumentIndexCoverageStatus.FAILED]
    cancelled_count = counts[DocumentIndexCoverageStatus.CANCELLED]

    ready = completed_count > 0
    reason = _readiness_reason(
        ready=ready,
        documents=documents,
        running_count=running_count,
        failed_count=failed_count,
    )
    return SearchReadinessSummary(
        ready=ready,
        reason=reason,
        active_index_version=_index_summary(index_version),
        completed_coverage_count=completed_count,
        running_coverage_count=running_count,
        failed_coverage_count=failed_count,
        cancelled_coverage_count=cancelled_count,
        documents=documents,
    )


async def require_searchable_content(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    retrieval_index_version_id: UUID,
) -> SearchReadinessSummary:
    return await get_search_readiness(
        session,
        tenant_id=tenant_id,
        retrieval_index_version_id=retrieval_index_version_id,
        recent_document_limit=25,
    )


async def _resolve_readiness_index_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    retrieval_index_version_id: UUID | None,
) -> RetrievalIndexVersion | None:
    if retrieval_index_version_id is not None:
        return await require_visible_index_version(
            session,
            tenant_id=tenant_id,
            retrieval_index_version_id=retrieval_index_version_id,
            require_active=True,
        )
    return await select_active_retrieval_index_version(
        session,
        tenant_id=tenant_id,
        configured_index_version_id=None,
    )


async def _load_coverage_totals(
    session: AsyncSession, *, tenant_id: UUID, index_version: RetrievalIndexVersion,
) -> dict[DocumentIndexCoverageStatus, int]:
    # Aggregate the full ledger independently of the recent-document UI preview.
    # Completed coverage is searchable only for currently active source versions,
    # matching primitive/query retrieval's authoritative source visibility filter.
    rows = await session.execute(
        select(DocumentIndexCoverage.status, DocumentVersion.status, func.count())
        .join(DocumentVersion, DocumentVersion.id == DocumentIndexCoverage.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            Document.tenant_id == tenant_id,
            Document.deleted_at.is_(None),
            DocumentIndexCoverage.tenant_id == tenant_id,
            DocumentIndexCoverage.document_id == Document.id,
            DocumentIndexCoverage.retrieval_index_version_id == index_version.id,
            DocumentVersion.status.notin_(
                [DocumentVersionStatus.DELETED, DocumentVersionStatus.SUPERSEDED]
            ),
        )
        .group_by(DocumentIndexCoverage.status, DocumentVersion.status)
    )
    counts = {status: 0 for status in DocumentIndexCoverageStatus}
    for coverage_status, version_status, count in rows:
        if (
            coverage_status == DocumentIndexCoverageStatus.COMPLETED
            and version_status != DocumentVersionStatus.ACTIVE
        ):
            continue
        counts[coverage_status] += count
    return counts


def _ranked_visible_versions(tenant_id: UUID) -> Subquery:
    return (
        select(
            DocumentVersion.id.label("version_id"),
            func.row_number().over(
                partition_by=DocumentVersion.document_id,
                order_by=(DocumentVersion.version_number.desc(), DocumentVersion.id.desc()),
            ).label("version_rank"),
        )
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            Document.tenant_id == tenant_id,
            Document.deleted_at.is_(None),
            DocumentVersion.status.notin_(
                [DocumentVersionStatus.DELETED, DocumentVersionStatus.SUPERSEDED]
            ),
        )
        .subquery()
    )


async def _load_recent_document_statuses(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    index_version: RetrievalIndexVersion,
    limit: int,
) -> list[SearchReadinessDocument]:
    ranked_versions = _ranked_visible_versions(tenant_id)
    rows = await session.execute(
        select(Document, DocumentVersion, DocumentIndexCoverage)
        .join(DocumentVersion, DocumentVersion.document_id == Document.id)
        .join(ranked_versions, ranked_versions.c.version_id == DocumentVersion.id)
        .outerjoin(
            DocumentIndexCoverage,
            (DocumentIndexCoverage.document_version_id == DocumentVersion.id)
            & (DocumentIndexCoverage.retrieval_index_version_id == index_version.id)
            & (DocumentIndexCoverage.tenant_id == tenant_id)
            & (DocumentIndexCoverage.document_id == Document.id),
            # Projection/ledger ownership is explicit even if a malformed legacy
            # row has valid but cross-tenant foreign keys.
        )
        .where(Document.tenant_id == tenant_id, ranked_versions.c.version_rank == 1)
        .where(Document.deleted_at.is_(None))
        .where(
            DocumentVersion.status.notin_(
                [DocumentVersionStatus.DELETED, DocumentVersionStatus.SUPERSEDED]
            )
        )
        .order_by(Document.updated_at.desc(), Document.id.desc())
        .limit(limit)
    )
    statuses: list[SearchReadinessDocument] = []
    for document, version, coverage in rows:
        statuses.append(
            SearchReadinessDocument(
                document_id=document.id,
                document_version_id=version.id,
                title=document.title,
                version_number=version.version_number,
                document_version_status=version.status,
                status=_document_readiness_status(version.status, coverage),
                coverage_status=coverage.status if coverage is not None else None,
                chunk_count=coverage.chunk_count if coverage is not None else 0,
                embedded_count=coverage.embedded_count if coverage is not None else 0,
                vector_count=coverage.vector_count if coverage is not None else 0,
                lexical_count=coverage.lexical_count if coverage is not None else 0,
                error_code=coverage.error_code if coverage is not None else None,
                error_message=coverage.error_message if coverage is not None else None,
                updated_at=max(document.updated_at, version.updated_at),
            )
        )
    return statuses


def _document_readiness_status(
    version_status: DocumentVersionStatus,
    coverage: DocumentIndexCoverage | None,
) -> str:
    if version_status == DocumentVersionStatus.FAILED:
        return "failed"
    if version_status == DocumentVersionStatus.CANCELLED:
        return "cancelled"
    if version_status == DocumentVersionStatus.DELETED:
        return "deleted"
    if version_status == DocumentVersionStatus.SUPERSEDED:
        return "superseded"
    if version_status == DocumentVersionStatus.PENDING:
        return "ingesting"
    if coverage is None:
        return "ingested"
    if coverage.status == DocumentIndexCoverageStatus.COMPLETED:
        return "searchable"
    if coverage.status == DocumentIndexCoverageStatus.RUNNING:
        return "indexing"
    if coverage.status == DocumentIndexCoverageStatus.FAILED:
        return "failed"
    if coverage.status == DocumentIndexCoverageStatus.CANCELLED:
        return "cancelled"
    return "ingested"


def _readiness_reason(
    *,
    ready: bool,
    documents: list[SearchReadinessDocument],
    running_count: int,
    failed_count: int,
) -> str:
    if ready:
        return "searchable"
    if not documents:
        return "no_documents"
    if running_count > 0:
        return "indexing_in_progress"
    if failed_count > 0:
        return "indexing_failed"
    return "no_completed_coverage"


def _index_summary(index_version: RetrievalIndexVersion) -> SearchReadinessIndexVersion:
    return SearchReadinessIndexVersion(
        id=index_version.id,
        embedding_provider=index_version.embedding_provider,
        embedding_model=index_version.embedding_model,
        vector_dimension=index_version.vector_dimension,
        opensearch_index_name=index_version.opensearch_index_name,
        neo4j_vector_index_name=index_version.neo4j_vector_index_name,
    )
