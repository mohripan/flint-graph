from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.outbox_contracts import IndexDocumentVersionPayload
from atlas_rag.domain.enums import (
    DocumentIndexCoverageStatus,
    DocumentVersionStatus,
    IndexBackfillJobStatus,
    RetrievalIndexScope,
)
from atlas_rag.domain.errors import NotFoundError
from atlas_rag.infrastructure.db.models import (
    ChunkEmbedding,
    Document,
    DocumentChunk,
    DocumentIndexCoverage,
    DocumentVersion,
    IndexBackfillJob,
    RetrievalIndexVersion,
)


@dataclass(frozen=True, slots=True)
class BackfillDocument:
    tenant_id: UUID
    document_id: UUID
    document_version_id: UUID
    retrieval_index_version_id: UUID

    def to_payload(self) -> IndexDocumentVersionPayload:
        return {
            "tenant_id": str(self.tenant_id),
            "document_id": str(self.document_id),
            "document_version_id": str(self.document_version_id),
            "retrieval_index_version_id": str(self.retrieval_index_version_id),
            "source": "backfill",
        }


@dataclass(frozen=True, slots=True)
class BackfillBatch:
    documents: list[BackfillDocument]
    done: bool

    def to_payload(self) -> dict[str, object]:
        return {
            "documents": [document.to_payload() for document in self.documents],
            "done": self.done,
        }


async def create_index_backfill_job(
    session: AsyncSession,
    *,
    retrieval_index_version_id: UUID,
    tenant_id: UUID | None = None,
    document_id: UUID | None = None,
    document_version_id: UUID | None = None,
) -> IndexBackfillJob:
    job = IndexBackfillJob(
        tenant_id=tenant_id,
        retrieval_index_version_id=retrieval_index_version_id,
        document_id=document_id,
        document_version_id=document_version_id,
        status=IndexBackfillJobStatus.QUEUED,
        total_count=0,
        processed_count=0,
        failed_count=0,
        checkpoint={},
    )
    session.add(job)
    await session.flush()
    return job


async def mark_backfill_running(
    session: AsyncSession,
    *,
    job_id: UUID,
) -> IndexBackfillJob:
    job = await _load_job_for_update(session, job_id)
    if job.status != IndexBackfillJobStatus.RUNNING:
        job.status = IndexBackfillJobStatus.RUNNING
        if job.started_at is None:
            job.started_at = datetime.now(UTC)
        job.completed_at = None
    await session.flush()
    return job


async def load_next_backfill_batch(
    session: AsyncSession,
    *,
    job_id: UUID,
    batch_size: int,
) -> BackfillBatch:
    job = await _load_job_for_update(session, job_id)
    candidates = await _eligible_backfill_documents(session, job)
    if job.total_count == 0:
        job.total_count = len(candidates)

    after_id = _checkpoint_after_document_version_id(job)
    if after_id is not None:
        candidates = _after_checkpoint(candidates, after_id)

    documents = candidates[:batch_size]
    await session.flush()
    return BackfillBatch(documents=documents, done=len(documents) == 0)


async def complete_backfill_document(
    session: AsyncSession,
    *,
    job_id: UUID,
    document_version_id: UUID,
) -> IndexBackfillJob:
    job = await _load_job_for_update(session, job_id)
    job.processed_count += 1
    job.checkpoint = {"after_document_version_id": str(document_version_id)}
    job.last_error = None
    await session.flush()
    return job


async def fail_backfill_document(
    session: AsyncSession,
    *,
    job_id: UUID,
    document_version_id: UUID,
    error_code: str,
    error_message: str,
) -> IndexBackfillJob:
    job = await _load_job_for_update(session, job_id)
    job.failed_count += 1
    job.checkpoint = {"after_document_version_id": str(document_version_id)}
    job.last_error = {
        "document_version_id": str(document_version_id),
        "code": error_code,
        "message": error_message[:500],
    }
    await session.flush()
    return job


async def complete_index_backfill(
    session: AsyncSession,
    *,
    job_id: UUID,
) -> IndexBackfillJob:
    job = await _load_job_for_update(session, job_id)
    job.status = IndexBackfillJobStatus.COMPLETED
    job.completed_at = datetime.now(UTC)
    job.last_error = None
    await session.flush()
    return job


async def fail_index_backfill(
    session: AsyncSession,
    *,
    job_id: UUID,
) -> IndexBackfillJob:
    job = await _load_job_for_update(session, job_id)
    job.status = IndexBackfillJobStatus.FAILED
    job.completed_at = datetime.now(UTC)
    await session.flush()
    return job


async def cancel_index_backfill(
    session: AsyncSession,
    *,
    job_id: UUID,
) -> IndexBackfillJob:
    job = await _load_job_for_update(session, job_id)
    job.status = IndexBackfillJobStatus.CANCELLED
    job.completed_at = datetime.now(UTC)
    await session.flush()
    return job


async def _eligible_backfill_documents(
    session: AsyncSession,
    job: IndexBackfillJob,
) -> list[BackfillDocument]:
    index_version = await _load_index_version(session, job.retrieval_index_version_id)
    tenant_filter = job.tenant_id
    if tenant_filter is None and index_version.scope == RetrievalIndexScope.TENANT:
        tenant_filter = index_version.tenant_id

    rows = (
        await session.execute(
            select(DocumentVersion, Document)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(
                Document.deleted_at.is_(None),
                DocumentVersion.status == DocumentVersionStatus.ACTIVE,
            )
            .order_by(
                Document.created_at,
                Document.title,
                DocumentVersion.created_at,
                DocumentVersion.id,
            )
        )
    ).all()

    documents: list[BackfillDocument] = []
    for version, document in rows:
        if tenant_filter is not None and document.tenant_id != tenant_filter:
            continue
        if job.document_id is not None and document.id != job.document_id:
            continue
        if job.document_version_id is not None and version.id != job.document_version_id:
            continue
        if await _document_needs_backfill(
            session,
            tenant_id=document.tenant_id,
            document_id=document.id,
            document_version_id=version.id,
            retrieval_index_version_id=index_version.id,
        ):
            documents.append(
                BackfillDocument(
                    tenant_id=document.tenant_id,
                    document_id=document.id,
                    document_version_id=version.id,
                    retrieval_index_version_id=index_version.id,
                )
            )
    return documents


async def _document_needs_backfill(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    document_version_id: UUID,
    retrieval_index_version_id: UUID,
) -> bool:
    chunk_count = await session.scalar(
        select(func.count(DocumentChunk.id)).where(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document_id,
            DocumentChunk.document_version_id == document_version_id,
        )
    )
    expected_count = int(chunk_count or 0)
    coverage = await session.scalar(
        select(DocumentIndexCoverage).where(
            DocumentIndexCoverage.tenant_id == tenant_id,
            DocumentIndexCoverage.document_version_id == document_version_id,
            DocumentIndexCoverage.retrieval_index_version_id == retrieval_index_version_id,
        )
    )
    if coverage is None:
        return True
    if coverage.status != DocumentIndexCoverageStatus.COMPLETED:
        return True
    if (
        coverage.chunk_count != expected_count
        or coverage.embedded_count != expected_count
        or coverage.vector_count != expected_count
        or coverage.lexical_count != expected_count
    ):
        return True

    current_embedding_count = await session.scalar(
        select(func.count(ChunkEmbedding.id))
        .join(
            DocumentChunk,
            (DocumentChunk.tenant_id == ChunkEmbedding.tenant_id)
            & (DocumentChunk.document_version_id == ChunkEmbedding.document_version_id)
            & (DocumentChunk.chunk_id == ChunkEmbedding.chunk_id)
            & (DocumentChunk.chunk_hash == ChunkEmbedding.chunk_hash),
        )
        .where(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document_id,
            DocumentChunk.document_version_id == document_version_id,
            ChunkEmbedding.retrieval_index_version_id == retrieval_index_version_id,
        )
    )
    return int(current_embedding_count or 0) != expected_count


async def _load_job_for_update(
    session: AsyncSession,
    job_id: UUID,
) -> IndexBackfillJob:
    job = await session.scalar(
        select(IndexBackfillJob)
        .where(IndexBackfillJob.id == job_id)
        .with_for_update()
    )
    if job is None:
        raise NotFoundError(f"Index backfill job '{job_id}' was not found.")
    return job


async def _load_index_version(
    session: AsyncSession,
    retrieval_index_version_id: UUID,
) -> RetrievalIndexVersion:
    index_version = await session.scalar(
        select(RetrievalIndexVersion).where(
            RetrievalIndexVersion.id == retrieval_index_version_id
        )
    )
    if index_version is None:
        raise NotFoundError(
            f"Retrieval index version '{retrieval_index_version_id}' was not found."
        )
    return index_version


def _checkpoint_after_document_version_id(job: IndexBackfillJob) -> UUID | None:
    value = job.checkpoint.get("after_document_version_id")
    return UUID(value) if isinstance(value, str) else None


def _after_checkpoint(
    candidates: list[BackfillDocument],
    after_id: UUID,
) -> list[BackfillDocument]:
    for index, candidate in enumerate(candidates):
        if candidate.document_version_id == after_id:
            return candidates[index + 1 :]
    return candidates
