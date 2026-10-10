from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from math import ceil
from typing import Any, Protocol, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.embeddings import (
    EmbeddingBatchRequest,
    EmbeddingInput,
    EmbeddingModel,
    EmbeddingProvider,
)
from flint_graph.application.services.lexical_projection import LexicalChunkRecord
from flint_graph.application.services.vector_projection import (
    SupportsCypher,
    VectorChunkRecord,
    build_create_vector_index_cypher,
    project_chunk_vectors,
)
from flint_graph.domain.enums import (
    DocumentIndexCoverageStatus,
    DocumentVersionStatus,
    RetrievalIndexScope,
    RetrievalIndexVersionStatus,
)
from flint_graph.domain.errors import ConflictError, NotFoundError
from flint_graph.infrastructure.db.models import (
    ChunkEmbedding,
    Document,
    DocumentChunk,
    DocumentIndexCoverage,
    DocumentVersion,
    RetrievalIndexVersion,
)
from flint_graph.infrastructure.opensearch import (
    build_chunk_index_mapping,
    build_upsert_chunks_bulk_body,
)


class SupportsOpenSearchBulk(Protocol):
    async def ensure_index(self, *, index_name: str, mapping: dict[str, Any]) -> None: ...

    async def bulk(self, *, body: str) -> None: ...


_INDEXABLE_DOCUMENT_VERSION_STATUSES = {
    DocumentVersionStatus.PENDING,
    DocumentVersionStatus.ACTIVE,
}


@dataclass(frozen=True, slots=True)
class DocumentIndexingPlan:
    chunk_count: int
    batch_count: int


@dataclass(frozen=True, slots=True)
class IndexingBatchRequest:
    tenant_id: UUID
    document_id: UUID
    document_version_id: UUID
    retrieval_index_version_id: UUID
    batch_index: int
    batch_size: int


@dataclass(frozen=True, slots=True)
class IndexingBatchResult:
    embedded_count: int
    vector_count: int
    lexical_count: int


@dataclass(frozen=True, slots=True)
class ReconcileIndexProjectionResult:
    vector_count: int
    lexical_count: int


async def select_active_retrieval_index_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    configured_index_version_id: UUID | None,
) -> RetrievalIndexVersion | None:
    if configured_index_version_id is not None:
        configured_version = await session.scalar(
            select(RetrievalIndexVersion).where(
                RetrievalIndexVersion.id == configured_index_version_id,
                RetrievalIndexVersion.status == RetrievalIndexVersionStatus.ACTIVE,
                (
                    RetrievalIndexVersion.scope == RetrievalIndexScope.GLOBAL
                )
                | (
                    (RetrievalIndexVersion.scope == RetrievalIndexScope.TENANT)
                    & (RetrievalIndexVersion.tenant_id == tenant_id)
                ),
            )
        )
        return configured_version

    tenant_version = await session.scalar(
        select(RetrievalIndexVersion).where(
            RetrievalIndexVersion.scope == RetrievalIndexScope.TENANT,
            RetrievalIndexVersion.tenant_id == tenant_id,
            RetrievalIndexVersion.status == RetrievalIndexVersionStatus.ACTIVE,
        )
    )
    if tenant_version is not None:
        return tenant_version

    global_version = await session.scalar(
        select(RetrievalIndexVersion).where(
            RetrievalIndexVersion.scope == RetrievalIndexScope.GLOBAL,
            RetrievalIndexVersion.tenant_id.is_(None),
            RetrievalIndexVersion.status == RetrievalIndexVersionStatus.ACTIVE,
        )
    )
    return global_version


async def plan_document_indexing(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    document_version_id: UUID,
    retrieval_index_version_id: UUID,
    batch_size: int,
) -> DocumentIndexingPlan:
    await _load_index_version(
        session,
        tenant_id=tenant_id,
        retrieval_index_version_id=retrieval_index_version_id,
    )
    await _require_indexable_document_version(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        document_version_id=document_version_id,
    )
    chunk_count = await _chunk_count(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        document_version_id=document_version_id,
    )
    await begin_document_indexing(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        document_version_id=document_version_id,
        retrieval_index_version_id=retrieval_index_version_id,
        chunk_count=chunk_count,
    )
    return DocumentIndexingPlan(
        chunk_count=chunk_count,
        batch_count=ceil(chunk_count / batch_size) if chunk_count else 0,
    )


async def begin_document_indexing(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    document_version_id: UUID,
    retrieval_index_version_id: UUID,
    chunk_count: int,
) -> DocumentIndexCoverage:
    await _require_indexable_document_version(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        document_version_id=document_version_id,
    )
    coverage = await _load_coverage(
        session,
        document_version_id=document_version_id,
        retrieval_index_version_id=retrieval_index_version_id,
    )
    now = datetime.now(UTC)
    if coverage is None:
        coverage = DocumentIndexCoverage(
            tenant_id=tenant_id,
            document_id=document_id,
            document_version_id=document_version_id,
            retrieval_index_version_id=retrieval_index_version_id,
        )
        session.add(coverage)

    coverage.status = DocumentIndexCoverageStatus.RUNNING
    coverage.chunk_count = chunk_count
    coverage.embedded_count = 0
    coverage.vector_count = 0
    coverage.lexical_count = 0
    coverage.started_at = now
    coverage.completed_at = None
    coverage.error_code = None
    coverage.error_message = None
    await session.flush()
    return coverage


async def complete_document_indexing(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_version_id: UUID,
    retrieval_index_version_id: UUID,
) -> DocumentIndexCoverage:
    coverage = await _require_coverage(
        session,
        tenant_id=tenant_id,
        document_version_id=document_version_id,
        retrieval_index_version_id=retrieval_index_version_id,
    )
    await _require_indexable_document_version(
        session,
        tenant_id=tenant_id,
        document_id=coverage.document_id,
        document_version_id=document_version_id,
    )
    coverage.status = DocumentIndexCoverageStatus.COMPLETED
    coverage.completed_at = datetime.now(UTC)
    coverage.error_code = None
    coverage.error_message = None
    await session.flush()
    return coverage


async def fail_document_indexing(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_version_id: UUID,
    retrieval_index_version_id: UUID,
    error_code: str,
    error_message: str,
) -> DocumentIndexCoverage:
    coverage = await _require_coverage(
        session,
        tenant_id=tenant_id,
        document_version_id=document_version_id,
        retrieval_index_version_id=retrieval_index_version_id,
    )
    if coverage.status == DocumentIndexCoverageStatus.CANCELLED:
        return coverage
    coverage.status = DocumentIndexCoverageStatus.FAILED
    coverage.completed_at = datetime.now(UTC)
    coverage.error_code = error_code
    coverage.error_message = error_message[:500]
    await session.flush()
    return coverage


async def cancel_document_indexing(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_version_id: UUID,
    retrieval_index_version_id: UUID,
) -> DocumentIndexCoverage:
    coverage = await _require_coverage(
        session,
        tenant_id=tenant_id,
        document_version_id=document_version_id,
        retrieval_index_version_id=retrieval_index_version_id,
    )
    coverage.status = DocumentIndexCoverageStatus.CANCELLED
    coverage.completed_at = datetime.now(UTC)
    await session.flush()
    return coverage


async def index_document_version_batch(
    session: AsyncSession,
    request: IndexingBatchRequest,
    *,
    embedding_model: EmbeddingModel,
    neo4j_client: SupportsCypher,
    opensearch_client: SupportsOpenSearchBulk,
) -> IndexingBatchResult:
    await _require_indexable_document_version(
        session,
        tenant_id=request.tenant_id,
        document_id=request.document_id,
        document_version_id=request.document_version_id,
    )
    index_version = await _load_index_version(
        session,
        tenant_id=request.tenant_id,
        retrieval_index_version_id=request.retrieval_index_version_id,
    )
    chunk_rows = await _load_chunk_batch(session, request)
    if not chunk_rows:
        return IndexingBatchResult(embedded_count=0, vector_count=0, lexical_count=0)

    embedding_request = EmbeddingBatchRequest(
        provider=cast(EmbeddingProvider, index_version.embedding_provider),
        model=index_version.embedding_model,
        dimensions=index_version.vector_dimension,
        inputs=[
            EmbeddingInput(
                input_id=chunk.chunk_id,
                text=chunk.text,
                metadata={"chunk_hash": chunk.chunk_hash},
            )
            for chunk, _document in chunk_rows
        ],
        max_batch_size=len(chunk_rows),
        config={"index_version_id": str(index_version.id)},
    )
    request_hash = _content_hash(embedding_request.model_dump_json().encode("utf-8"))
    embedding_result = await embedding_model.embed_batch(embedding_request)
    embeddings_by_id = {
        embedding.input_id: embedding for embedding in embedding_result.embeddings
    }

    vector_records: list[VectorChunkRecord] = []
    lexical_records: list[LexicalChunkRecord] = []
    for chunk, document in chunk_rows:
        embedding = embeddings_by_id.get(chunk.chunk_id)
        if embedding is None:
            raise ValueError(f"embedding result omitted chunk '{chunk.chunk_id}'.")
        await _upsert_chunk_embedding(
            session,
            tenant_id=request.tenant_id,
            document_id=request.document_id,
            document_version_id=request.document_version_id,
            retrieval_index_version_id=request.retrieval_index_version_id,
            chunk_id=chunk.chunk_id,
            chunk_hash=chunk.chunk_hash,
            vector_dimension=embedding_result.dimensions,
            vector=embedding.vector,
            provider_metadata=embedding.metadata | embedding_result.metadata,
            request_hash=request_hash,
        )
        metadata = {
            "chunk_index": chunk.chunk_index,
            "heading_path": chunk.heading_path,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
        }
        vector_records.append(
            VectorChunkRecord(
                tenant_id=request.tenant_id,
                document_id=request.document_id,
                document_version_id=request.document_version_id,
                chunk_id=chunk.chunk_id,
                chunk_hash=chunk.chunk_hash,
                retrieval_index_version_id=request.retrieval_index_version_id,
                vector=embedding.vector,
                text_preview=chunk.text[:200],
                metadata=metadata,
            )
        )
        lexical_records.append(
            LexicalChunkRecord(
                tenant_id=request.tenant_id,
                document_id=request.document_id,
                document_version_id=request.document_version_id,
                chunk_id=chunk.chunk_id,
                chunk_hash=chunk.chunk_hash,
                title=document.title,
                text=chunk.text,
                heading_path=chunk.heading_path,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                source_uri=document.source_uri,
                metadata=chunk.metadata_,
            )
        )

    await session.flush()
    await neo4j_client.execute(
        build_create_vector_index_cypher(
            index_name=index_version.neo4j_vector_index_name,
            label="Chunk",
            property_name=index_version.neo4j_vector_property_name,
            dimensions=index_version.vector_dimension,
        )
    )
    await project_chunk_vectors(
        neo4j_client,
        records=vector_records,
        vector_property_name=index_version.neo4j_vector_property_name,
    )
    await opensearch_client.ensure_index(
        index_name=index_version.opensearch_index_name,
        mapping=build_chunk_index_mapping(),
    )
    await opensearch_client.bulk(
        body=build_upsert_chunks_bulk_body(
            index_name=index_version.opensearch_index_name,
            records=lexical_records,
            index_version_id=index_version.id,
        )
    )
    await _mark_batch_counts(
        session,
        request=request,
        projected_count=len(vector_records),
        lexical_count=len(lexical_records),
    )
    return IndexingBatchResult(
        embedded_count=len(embeddings_by_id),
        vector_count=len(vector_records),
        lexical_count=len(lexical_records),
    )


async def _require_indexable_document_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    document_version_id: UUID,
) -> DocumentVersion:
    document = await session.scalar(select(Document).where(
        Document.id == document_id, Document.tenant_id == tenant_id,
    ).with_for_update().execution_options(populate_existing=True))
    if document is None:
        raise NotFoundError(f"Document version '{document_version_id}' was not found.")
    row = await session.execute(
        select(DocumentVersion, Document)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            Document.tenant_id == tenant_id,
            Document.id == document_id,
            DocumentVersion.id == document_version_id,
        )
        .with_for_update(of=DocumentVersion)
        .execution_options(populate_existing=True)
    )
    version_and_document = row.one_or_none()
    if version_and_document is None:
        raise NotFoundError(f"Document version '{document_version_id}' was not found.")
    version = cast(DocumentVersion, version_and_document[0])
    document = cast(Document, version_and_document[1])
    if document.deleted_at is not None:
        raise ConflictError(f"Document '{document_id}' has been deleted.")
    if version.status not in _INDEXABLE_DOCUMENT_VERSION_STATUSES:
        raise ConflictError(
            f"Cannot index document version '{document_version_id}' in "
            f"'{version.status}' status."
        )
    return version


async def _load_index_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    retrieval_index_version_id: UUID,
) -> RetrievalIndexVersion:
    version = await session.scalar(
        select(RetrievalIndexVersion).where(
            RetrievalIndexVersion.id == retrieval_index_version_id,
            RetrievalIndexVersion.status == RetrievalIndexVersionStatus.ACTIVE,
            (
                (RetrievalIndexVersion.scope == RetrievalIndexScope.GLOBAL)
                & RetrievalIndexVersion.tenant_id.is_(None)
            )
            | (
                (RetrievalIndexVersion.scope == RetrievalIndexScope.TENANT)
                & (RetrievalIndexVersion.tenant_id == tenant_id)
            ),
        )
    )
    if version is None:
        raise NotFoundError(
            f"Retrieval index version '{retrieval_index_version_id}' was not found."
        )
    return version


async def _load_chunk_batch(
    session: AsyncSession,
    request: IndexingBatchRequest,
) -> list[tuple[DocumentChunk, Document]]:
    result = await session.execute(
        select(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            DocumentChunk.tenant_id == request.tenant_id,
            DocumentChunk.document_id == request.document_id,
            DocumentChunk.document_version_id == request.document_version_id,
        )
        .order_by(DocumentChunk.chunk_index)
        .offset(request.batch_index * request.batch_size)
        .limit(request.batch_size)
    )
    return [(chunk, document) for chunk, document in result.all()]


async def _chunk_count(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    document_version_id: UUID,
) -> int:
    count = await session.scalar(
        select(func.count(DocumentChunk.id)).where(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document_id,
            DocumentChunk.document_version_id == document_version_id,
        )
    )
    return int(count or 0)


async def _upsert_chunk_embedding(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    document_version_id: UUID,
    retrieval_index_version_id: UUID,
    chunk_id: str,
    chunk_hash: str,
    vector_dimension: int,
    vector: list[float],
    provider_metadata: dict[str, Any],
    request_hash: str,
) -> None:
    existing = await session.scalar(
        select(ChunkEmbedding).where(
            ChunkEmbedding.retrieval_index_version_id == retrieval_index_version_id,
            ChunkEmbedding.document_version_id == document_version_id,
            ChunkEmbedding.chunk_id == chunk_id,
            ChunkEmbedding.chunk_hash == chunk_hash,
        )
    )
    if existing is None:
        session.add(
            ChunkEmbedding(
                tenant_id=tenant_id,
                document_id=document_id,
                document_version_id=document_version_id,
                retrieval_index_version_id=retrieval_index_version_id,
                chunk_id=chunk_id,
                chunk_hash=chunk_hash,
                vector_dimension=vector_dimension,
                vector=vector,
                provider_metadata=provider_metadata,
                request_hash=request_hash,
            )
        )
        return

    existing.vector_dimension = vector_dimension
    existing.vector = vector
    existing.provider_metadata = provider_metadata
    existing.request_hash = request_hash


async def _mark_batch_counts(
    session: AsyncSession,
    *,
    request: IndexingBatchRequest,
    projected_count: int,
    lexical_count: int,
) -> None:
    coverage = await _require_coverage(
        session,
        tenant_id=request.tenant_id,
        document_version_id=request.document_version_id,
        retrieval_index_version_id=request.retrieval_index_version_id,
    )
    embedded_count = await session.scalar(
        select(func.count(ChunkEmbedding.id)).where(
            ChunkEmbedding.tenant_id == request.tenant_id,
            ChunkEmbedding.document_version_id == request.document_version_id,
            ChunkEmbedding.retrieval_index_version_id == request.retrieval_index_version_id,
        )
    )
    cumulative_embeddings = int(embedded_count or 0)
    coverage.embedded_count = cumulative_embeddings
    coverage.vector_count = max(coverage.vector_count, min(coverage.chunk_count, projected_count))
    coverage.lexical_count = max(coverage.lexical_count, min(coverage.chunk_count, lexical_count))
    if cumulative_embeddings > coverage.vector_count:
        coverage.vector_count = cumulative_embeddings
    if cumulative_embeddings > coverage.lexical_count:
        coverage.lexical_count = cumulative_embeddings
    await session.flush()


async def _load_coverage(
    session: AsyncSession,
    *,
    document_version_id: UUID,
    retrieval_index_version_id: UUID,
) -> DocumentIndexCoverage | None:
    coverage = await session.scalar(
        select(DocumentIndexCoverage).where(
            DocumentIndexCoverage.document_version_id == document_version_id,
            DocumentIndexCoverage.retrieval_index_version_id == retrieval_index_version_id,
        )
    )
    return coverage


async def _require_coverage(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_version_id: UUID,
    retrieval_index_version_id: UUID,
) -> DocumentIndexCoverage:
    # Completion/failure used to lock coverage before the document, opposite
    # deletion's order. All indexing mutations now take Document first.
    document = await session.scalar(
        select(Document)
        .join(DocumentIndexCoverage, DocumentIndexCoverage.document_id == Document.id)
        .where(
            Document.tenant_id == tenant_id,
            DocumentIndexCoverage.tenant_id == tenant_id,
            DocumentIndexCoverage.document_version_id == document_version_id,
            DocumentIndexCoverage.retrieval_index_version_id == retrieval_index_version_id,
        ).with_for_update(of=Document).execution_options(populate_existing=True)
    )
    if document is None:
        raise NotFoundError("Document index coverage was not found.")
    coverage = await session.scalar(
        select(DocumentIndexCoverage)
        .where(
            DocumentIndexCoverage.tenant_id == tenant_id,
            DocumentIndexCoverage.document_version_id == document_version_id,
            DocumentIndexCoverage.retrieval_index_version_id == retrieval_index_version_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if coverage is None:
        raise NotFoundError(
            "Document index coverage was not found for document version "
            f"'{document_version_id}'."
        )
    return coverage


def _content_hash(data: bytes) -> str:
    return "sha256:" + sha256(data).hexdigest()


def payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _content_hash(encoded)


async def reconcile_document_index_projection(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_version_id: UUID,
    retrieval_index_version_id: UUID,
    neo4j_client: SupportsCypher,
    opensearch_client: SupportsOpenSearchBulk,
) -> ReconcileIndexProjectionResult:
    index_version = await _load_index_version(
        session,
        tenant_id=tenant_id,
        retrieval_index_version_id=retrieval_index_version_id,
    )
    rows = (
        await session.execute(
            select(DocumentChunk, Document, ChunkEmbedding)
            .join(Document, Document.id == DocumentChunk.document_id)
            .outerjoin(
                ChunkEmbedding,
                (ChunkEmbedding.tenant_id == DocumentChunk.tenant_id)
                & (ChunkEmbedding.document_version_id == DocumentChunk.document_version_id)
                & (ChunkEmbedding.chunk_id == DocumentChunk.chunk_id)
                & (ChunkEmbedding.chunk_hash == DocumentChunk.chunk_hash)
                & (
                    ChunkEmbedding.retrieval_index_version_id
                    == retrieval_index_version_id
                ),
            )
            .where(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.document_version_id == document_version_id,
            )
            .order_by(DocumentChunk.chunk_index)
        )
    ).all()
    if not rows:
        return ReconcileIndexProjectionResult(vector_count=0, lexical_count=0)

    vector_records: list[VectorChunkRecord] = []
    lexical_records: list[LexicalChunkRecord] = []
    for chunk, document, embedding in rows:
        if embedding is None:
            raise RuntimeError("missing current chunk embeddings for document version")
        metadata = {
            "chunk_index": chunk.chunk_index,
            "heading_path": chunk.heading_path,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
        }
        vector_records.append(
            VectorChunkRecord(
                tenant_id=tenant_id,
                document_id=chunk.document_id,
                document_version_id=chunk.document_version_id,
                chunk_id=chunk.chunk_id,
                chunk_hash=chunk.chunk_hash,
                retrieval_index_version_id=retrieval_index_version_id,
                vector=embedding.vector,
                text_preview=chunk.text[:200],
                metadata=metadata,
            )
        )
        lexical_records.append(
            LexicalChunkRecord(
                tenant_id=tenant_id,
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
            )
        )

    await project_chunk_vectors(
        neo4j_client,
        records=vector_records,
        vector_property_name=index_version.neo4j_vector_property_name,
    )
    await opensearch_client.bulk(
        body=build_upsert_chunks_bulk_body(
            index_name=index_version.opensearch_index_name,
            records=lexical_records,
            index_version_id=index_version.id,
        )
    )
    return ReconcileIndexProjectionResult(
        vector_count=len(vector_records),
        lexical_count=len(lexical_records),
    )


async def reconcile_completed_index_projections(
    session: AsyncSession,
    *,
    neo4j_client: SupportsCypher,
    opensearch_client: SupportsOpenSearchBulk,
    tenant_id: UUID | None = None,
    retrieval_index_version_id: UUID | None = None,
) -> int:
    statement = select(DocumentIndexCoverage).where(
        DocumentIndexCoverage.status == DocumentIndexCoverageStatus.COMPLETED
    )
    if tenant_id is not None:
        statement = statement.where(DocumentIndexCoverage.tenant_id == tenant_id)
    if retrieval_index_version_id is not None:
        statement = statement.where(
            DocumentIndexCoverage.retrieval_index_version_id
            == retrieval_index_version_id
        )
    coverages = list(
        await session.scalars(statement.order_by(DocumentIndexCoverage.created_at))
    )

    reconciled = 0
    for coverage in coverages:
        await reconcile_document_index_projection(
            session,
            tenant_id=coverage.tenant_id,
            document_version_id=coverage.document_version_id,
            retrieval_index_version_id=coverage.retrieval_index_version_id,
            neo4j_client=neo4j_client,
            opensearch_client=opensearch_client,
        )
        reconciled += 1
    return reconciled
