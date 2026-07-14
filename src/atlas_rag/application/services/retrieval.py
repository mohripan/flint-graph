from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.embeddings import (
    EmbeddingBatchRequest,
    EmbeddingInput,
    EmbeddingModel,
    EmbeddingProvider,
)
from atlas_rag.application.services.index_backfill import create_index_backfill_job
from atlas_rag.application.services.indexing import select_active_retrieval_index_version
from atlas_rag.application.services.lexical_projection import build_lexical_search_body
from atlas_rag.domain.enums import (
    DocumentIndexCoverageStatus,
    EntityStatus,
    RelationshipStatus,
    RetrievalIndexScope,
    RetrievalIndexVersionStatus,
)
from atlas_rag.domain.errors import NotFoundError
from atlas_rag.infrastructure.db.models import (
    CanonicalEntity,
    Document,
    DocumentIndexCoverage,
    DocumentVersion,
    EntityRelationship,
    IndexBackfillJob,
    RetrievalIndexVersion,
)


class SupportsOpenSearchSearch(Protocol):
    async def search(self, *, index_name: str, body: dict[str, Any]) -> list[dict[str, Any]]: ...


class SupportsCypherSearch(Protocol):
    async def execute(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class RetrievalChunkResult:
    score: float
    tenant_id: UUID
    document_id: UUID
    document_version_id: UUID
    chunk_id: str
    chunk_hash: str
    text: str | None
    title: str | None
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    source_uri: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RetrievalSearchResult:
    index_version: RetrievalIndexVersion
    results: list[RetrievalChunkResult]


@dataclass(frozen=True, slots=True)
class EntityNeighborhood:
    root_entity_id: UUID
    depth: int
    entities: list[CanonicalEntity]
    relationships: list[EntityRelationship]


VECTOR_SEARCH_CYPHER = """
CALL db.index.vector.queryNodes($index_name, $candidate_limit, $vector)
YIELD node, score
WHERE node.tenant_id = $tenant_id
  AND node.retrieval_index_version_id = $retrieval_index_version_id
  AND ($document_id IS NULL OR node.document_id = $document_id)
  AND ($document_version_id IS NULL OR node.document_version_id = $document_version_id)
  AND ($chunk_id IS NULL OR node.chunk_id = $chunk_id)
RETURN node, score
ORDER BY score DESC
LIMIT $limit
"""


async def list_index_versions(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    status: RetrievalIndexVersionStatus | None = None,
    limit: int = 100,
) -> list[RetrievalIndexVersion]:
    statement = select(RetrievalIndexVersion).where(
        (
            (RetrievalIndexVersion.scope == RetrievalIndexScope.GLOBAL)
            & RetrievalIndexVersion.tenant_id.is_(None)
        )
        | (
            (RetrievalIndexVersion.scope == RetrievalIndexScope.TENANT)
            & (RetrievalIndexVersion.tenant_id == tenant_id)
        )
    )
    if status is not None:
        statement = statement.where(RetrievalIndexVersion.status == status)
    rows = await session.scalars(
        statement.order_by(RetrievalIndexVersion.created_at.desc()).limit(limit)
    )
    return list(rows)


async def list_index_coverage(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    retrieval_index_version_id: UUID | None = None,
    document_id: UUID | None = None,
    document_version_id: UUID | None = None,
    status: DocumentIndexCoverageStatus | None = None,
    limit: int = 100,
) -> list[DocumentIndexCoverage]:
    await _validate_document_scope(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        document_version_id=document_version_id,
    )
    if retrieval_index_version_id is not None:
        await require_visible_index_version(
            session,
            tenant_id=tenant_id,
            retrieval_index_version_id=retrieval_index_version_id,
            require_active=False,
        )

    statement = select(DocumentIndexCoverage).where(DocumentIndexCoverage.tenant_id == tenant_id)
    if retrieval_index_version_id is not None:
        statement = statement.where(
            DocumentIndexCoverage.retrieval_index_version_id == retrieval_index_version_id
        )
    if document_id is not None:
        statement = statement.where(DocumentIndexCoverage.document_id == document_id)
    if document_version_id is not None:
        statement = statement.where(
            DocumentIndexCoverage.document_version_id == document_version_id
        )
    if status is not None:
        statement = statement.where(DocumentIndexCoverage.status == status)

    rows = await session.scalars(
        statement.order_by(DocumentIndexCoverage.created_at.desc()).limit(limit)
    )
    return list(rows)


async def create_tenant_index_backfill_job(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    retrieval_index_version_id: UUID,
    document_id: UUID | None = None,
    document_version_id: UUID | None = None,
) -> IndexBackfillJob:
    await require_visible_index_version(
        session,
        tenant_id=tenant_id,
        retrieval_index_version_id=retrieval_index_version_id,
        require_active=False,
    )
    await _validate_document_scope(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        document_version_id=document_version_id,
    )
    return await create_index_backfill_job(
        session,
        tenant_id=tenant_id,
        retrieval_index_version_id=retrieval_index_version_id,
        document_id=document_id,
        document_version_id=document_version_id,
    )


async def get_tenant_index_backfill_job(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    job_id: UUID,
) -> IndexBackfillJob:
    job = await session.get(IndexBackfillJob, job_id)
    if job is None or job.tenant_id != tenant_id:
        raise NotFoundError(f"Index backfill job '{job_id}' was not found.")
    return job


async def lexical_search(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    opensearch_client: SupportsOpenSearchSearch,
    query: str,
    limit: int,
    retrieval_index_version_id: UUID | None = None,
    filters: dict[str, Any] | None = None,
) -> RetrievalSearchResult:
    index_version = await resolve_index_version(
        session,
        tenant_id=tenant_id,
        retrieval_index_version_id=retrieval_index_version_id,
    )
    resolved_filters = dict(filters or {})
    resolved_filters["index_version_id"] = index_version.id
    hits = await opensearch_client.search(
        index_name=index_version.opensearch_index_name,
        body=build_lexical_search_body(
            tenant_id=tenant_id,
            query=query,
            limit=limit,
            filters=resolved_filters,
        ),
    )
    return RetrievalSearchResult(
        index_version=index_version,
        results=[_chunk_result_from_opensearch_hit(hit) for hit in hits],
    )


async def vector_search(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    neo4j_client: SupportsCypherSearch,
    embedding_model: EmbeddingModel,
    query: str,
    limit: int,
    retrieval_index_version_id: UUID | None = None,
    filters: dict[str, Any] | None = None,
) -> RetrievalSearchResult:
    index_version = await resolve_index_version(
        session,
        tenant_id=tenant_id,
        retrieval_index_version_id=retrieval_index_version_id,
    )
    embedding_result = await embedding_model.embed_batch(
        EmbeddingBatchRequest(
            provider=cast(EmbeddingProvider, index_version.embedding_provider),
            model=index_version.embedding_model,
            dimensions=index_version.vector_dimension,
            inputs=[
                EmbeddingInput(
                    input_id="query",
                    text=query,
                    metadata={"purpose": "vector_search"},
                )
            ],
            max_batch_size=1,
            config={"index_version_id": str(index_version.id)},
        )
    )
    vector = embedding_result.embeddings[0].vector
    resolved_filters = dict(filters or {})
    rows = await neo4j_client.execute(
        VECTOR_SEARCH_CYPHER,
        {
            "index_name": index_version.neo4j_vector_index_name,
            "candidate_limit": min(max(limit * 5, limit), 500),
            "vector": vector,
            "tenant_id": str(tenant_id),
            "retrieval_index_version_id": str(index_version.id),
            "document_id": _filter_uuid_string(resolved_filters, "document_id"),
            "document_version_id": _filter_uuid_string(resolved_filters, "document_version_id"),
            "chunk_id": resolved_filters.get("chunk_id"),
            "limit": limit,
        },
    )
    return RetrievalSearchResult(
        index_version=index_version,
        results=[_chunk_result_from_neo4j_row(row) for row in rows],
    )


async def load_entity_neighborhood(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    entity_id: UUID,
    depth: int,
    limit: int,
) -> EntityNeighborhood:
    root = await session.get(CanonicalEntity, entity_id)
    if root is None or root.tenant_id != tenant_id:
        raise NotFoundError(f"Canonical entity '{entity_id}' was not found.")

    entity_ids: set[UUID] = {entity_id}
    relationship_ids: set[UUID] = set()
    frontier: set[UUID] = {entity_id}
    for _ in range(depth):
        if not frontier or len(relationship_ids) >= limit:
            break
        relationships = list(
            await session.scalars(
                select(EntityRelationship)
                .where(
                    EntityRelationship.tenant_id == tenant_id,
                    EntityRelationship.status == RelationshipStatus.ACTIVE,
                    (EntityRelationship.subject_entity_id.in_(frontier))
                    | (EntityRelationship.object_entity_id.in_(frontier)),
                )
                .order_by(EntityRelationship.support_count.desc(), EntityRelationship.id)
                .limit(limit - len(relationship_ids))
            )
        )
        next_frontier: set[UUID] = set()
        for relationship in relationships:
            if relationship.id in relationship_ids:
                continue
            relationship_ids.add(relationship.id)
            for related_id in (
                relationship.subject_entity_id,
                relationship.object_entity_id,
            ):
                if related_id not in entity_ids:
                    entity_ids.add(related_id)
                    next_frontier.add(related_id)
        frontier = next_frontier

    entities = list(
        await session.scalars(
            select(CanonicalEntity)
            .where(
                CanonicalEntity.tenant_id == tenant_id,
                CanonicalEntity.id.in_(entity_ids),
                CanonicalEntity.status != EntityStatus.MERGED,
            )
            .order_by(CanonicalEntity.canonical_name)
        )
    )
    relationships = list(
        await session.scalars(
            select(EntityRelationship)
            .where(EntityRelationship.id.in_(relationship_ids))
            .order_by(EntityRelationship.support_count.desc(), EntityRelationship.id)
        )
    )
    return EntityNeighborhood(
        root_entity_id=entity_id,
        depth=depth,
        entities=entities,
        relationships=relationships,
    )


async def resolve_index_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    retrieval_index_version_id: UUID | None,
) -> RetrievalIndexVersion:
    if retrieval_index_version_id is not None:
        return await require_visible_index_version(
            session,
            tenant_id=tenant_id,
            retrieval_index_version_id=retrieval_index_version_id,
            require_active=True,
        )
    index_version = await select_active_retrieval_index_version(
        session,
        tenant_id=tenant_id,
        configured_index_version_id=None,
    )
    if index_version is None:
        raise NotFoundError("No active retrieval index version was found.")
    return index_version


async def require_visible_index_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    retrieval_index_version_id: UUID,
    require_active: bool,
) -> RetrievalIndexVersion:
    statement = select(RetrievalIndexVersion).where(
        RetrievalIndexVersion.id == retrieval_index_version_id,
        (
            (RetrievalIndexVersion.scope == RetrievalIndexScope.GLOBAL)
            & RetrievalIndexVersion.tenant_id.is_(None)
        )
        | (
            (RetrievalIndexVersion.scope == RetrievalIndexScope.TENANT)
            & (RetrievalIndexVersion.tenant_id == tenant_id)
        ),
    )
    if require_active:
        statement = statement.where(
            RetrievalIndexVersion.status == RetrievalIndexVersionStatus.ACTIVE
        )
    index_version = await session.scalar(statement)
    if index_version is None:
        raise NotFoundError(
            f"Retrieval index version '{retrieval_index_version_id}' was not found."
        )
    return index_version


async def _validate_document_scope(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID | None,
    document_version_id: UUID | None,
) -> None:
    if document_id is None and document_version_id is None:
        return
    if document_id is not None:
        document = await session.get(Document, document_id)
        if document is None or document.tenant_id != tenant_id:
            raise NotFoundError(f"Document '{document_id}' was not found.")
    if document_version_id is not None:
        version = await session.get(DocumentVersion, document_version_id)
        if version is None:
            raise NotFoundError(f"Document version '{document_version_id}' was not found.")
        if document_id is not None and version.document_id != document_id:
            raise NotFoundError(f"Document version '{document_version_id}' was not found.")
        if document_id is None:
            document = await session.get(Document, version.document_id)
            if document is None or document.tenant_id != tenant_id:
                raise NotFoundError(f"Document version '{document_version_id}' was not found.")


def _chunk_result_from_opensearch_hit(hit: dict[str, Any]) -> RetrievalChunkResult:
    source = hit.get("source")
    if not isinstance(source, dict):
        source = {}
    return RetrievalChunkResult(
        score=float(hit.get("score") or 0.0),
        tenant_id=UUID(str(source["tenant_id"])),
        document_id=UUID(str(source["document_id"])),
        document_version_id=UUID(str(source["document_version_id"])),
        chunk_id=str(source["chunk_id"]),
        chunk_hash=str(source["chunk_hash"]),
        text=source.get("text"),
        title=source.get("title"),
        heading_path=list(source.get("heading_path") or []),
        page_start=source.get("page_start"),
        page_end=source.get("page_end"),
        source_uri=source.get("source_uri"),
        metadata=dict(source.get("metadata") or {}),
    )


def _chunk_result_from_neo4j_row(row: dict[str, Any]) -> RetrievalChunkResult:
    node = row.get("node")
    if not isinstance(node, dict):
        node = {}
    metadata_raw = node.get("metadata_json")
    metadata = json.loads(metadata_raw) if isinstance(metadata_raw, str) else {}
    return RetrievalChunkResult(
        score=float(row.get("score") or 0.0),
        tenant_id=UUID(str(node["tenant_id"])),
        document_id=UUID(str(node["document_id"])),
        document_version_id=UUID(str(node["document_version_id"])),
        chunk_id=str(node["chunk_id"]),
        chunk_hash=str(node["chunk_hash"]),
        text=node.get("text_preview"),
        title=None,
        heading_path=list(metadata.get("heading_path") or []),
        page_start=metadata.get("page_start"),
        page_end=metadata.get("page_end"),
        source_uri=None,
        metadata=metadata,
    )


def _filter_uuid_string(filters: dict[str, Any], name: str) -> str | None:
    value = filters.get(name)
    return str(value) if value is not None else None
