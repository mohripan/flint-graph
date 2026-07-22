from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.embeddings import (
    EmbeddingBatchRequest,
    EmbeddingBatchResult,
    EmbeddingModel,
    EmbeddingVector,
)
from flint_graph.application.services.indexing import (
    IndexingBatchRequest,
    begin_document_indexing,
    complete_document_indexing,
    fail_document_indexing,
    index_document_version_batch,
    plan_document_indexing,
    select_active_retrieval_index_version,
)
from flint_graph.application.services.retrieval_index_versions import (
    RetrievalIndexVersionSpec,
    activate_retrieval_index_version,
    create_retrieval_index_version,
)
from flint_graph.domain.enums import (
    DocumentIndexCoverageStatus,
    DocumentVersionStatus,
    RetrievalIndexScope,
    SourceType,
)
from flint_graph.infrastructure.db.models import (
    ChunkEmbedding,
    Document,
    DocumentChunk,
    DocumentVersion,
    RetrievalIndexVersion,
    Tenant,
)


class FakeEmbeddingModel(EmbeddingModel):
    def __init__(self) -> None:
        self.requests: list[EmbeddingBatchRequest] = []

    async def embed_batch(self, request: EmbeddingBatchRequest) -> EmbeddingBatchResult:
        self.requests.append(request)
        return EmbeddingBatchResult(
            provider=request.provider,
            model=request.model,
            dimensions=request.dimensions,
            embeddings=[
                EmbeddingVector(
                    input_id=item.input_id,
                    vector=[float(index + 1)] * request.dimensions,
                    metadata={"ordinal": index},
                )
                for index, item in enumerate(request.inputs)
            ],
        )


class FakeNeo4jClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append((query, parameters or {}))
        return []


class FakeOpenSearchClient:
    def __init__(self) -> None:
        self.bulk_bodies: list[str] = []

    async def bulk(self, *, body: str) -> None:
        self.bulk_bodies.append(body)


async def _seed_indexable_document(
    session: AsyncSession,
) -> tuple[Tenant, Document, DocumentVersion, RetrievalIndexVersion]:
    tenant = Tenant(name="indexing-service")
    session.add(tenant)
    await session.flush()

    document = Document(
        tenant_id=tenant.id,
        title="Indexing Doc",
        source_type=SourceType.UPLOAD,
        source_uri="s3://flint-graph/source.md",
        next_version_number=2,
    )
    session.add(document)
    await session.flush()

    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        status=DocumentVersionStatus.ACTIVE,
        content_hash="sha256:document",
    )
    session.add(version)
    await session.flush()

    session.add_all(
        [
            DocumentChunk(
                tenant_id=tenant.id,
                document_id=document.id,
                document_version_id=version.id,
                chunk_id="chunk-000001",
                chunk_index=0,
                text="Acme Corporation is headquartered in Berlin.",
                chunk_hash="sha256:chunk-1",
                heading_path=["Overview"],
            ),
            DocumentChunk(
                tenant_id=tenant.id,
                document_id=document.id,
                document_version_id=version.id,
                chunk_id="chunk-000002",
                chunk_index=1,
                text="FlintGraph stores retrieval projections outside PostgreSQL.",
                chunk_hash="sha256:chunk-2",
                page_start=2,
                page_end=3,
            ),
        ]
    )
    index_version = await create_retrieval_index_version(
        session,
        scope=RetrievalIndexScope.TENANT,
        tenant_id=tenant.id,
        spec=RetrievalIndexVersionSpec(
            embedding_provider="deterministic",
            embedding_model="deterministic-test",
            vector_dimension=4,
            embedding_config_hash="sha256:embedding",
            chunking_schema_version="1",
            chunking_config_hash="sha256:chunking",
            lexical_schema_version="1",
            neo4j_vector_index_name="chunk_embedding_test",
            neo4j_vector_property_name="embedding",
            opensearch_index_name="flint_graph_chunks_v000001",
            opensearch_alias_name="flint_graph_chunks_active",
        ),
    )
    await activate_retrieval_index_version(session, version_id=index_version.id)
    await session.flush()
    return tenant, document, version, index_version


async def test_select_active_retrieval_index_version_prefers_tenant_scope(
    db_session: AsyncSession,
) -> None:
    tenant, _document, _version, tenant_index_version = await _seed_indexable_document(
        db_session
    )
    global_index_version = await create_retrieval_index_version(
        db_session,
        scope=RetrievalIndexScope.GLOBAL,
        spec=RetrievalIndexVersionSpec(
            embedding_provider="deterministic",
            embedding_model="global",
            vector_dimension=4,
            embedding_config_hash="sha256:global",
            chunking_schema_version="1",
            chunking_config_hash="sha256:chunking",
            lexical_schema_version="1",
            neo4j_vector_index_name="chunk_embedding_global",
            neo4j_vector_property_name="embedding",
            opensearch_index_name="flint_graph_chunks_global",
            opensearch_alias_name="flint_graph_chunks_active",
        ),
    )
    await activate_retrieval_index_version(db_session, version_id=global_index_version.id)

    selected = await select_active_retrieval_index_version(
        db_session,
        tenant_id=tenant.id,
        configured_index_version_id=None,
    )

    assert selected is not None
    assert selected.id == tenant_index_version.id


async def test_index_document_version_batch_persists_embeddings_and_updates_projections(
    db_session: AsyncSession,
) -> None:
    tenant, document, version, index_version = await _seed_indexable_document(db_session)
    embedding_model = FakeEmbeddingModel()
    neo4j_client = FakeNeo4jClient()
    opensearch_client = FakeOpenSearchClient()

    plan = await plan_document_indexing(
        db_session,
        tenant_id=tenant.id,
        document_id=document.id,
        document_version_id=version.id,
        retrieval_index_version_id=index_version.id,
        batch_size=10,
    )
    coverage = await begin_document_indexing(
        db_session,
        tenant_id=tenant.id,
        document_id=document.id,
        document_version_id=version.id,
        retrieval_index_version_id=index_version.id,
        chunk_count=plan.chunk_count,
    )
    result = await index_document_version_batch(
        db_session,
        IndexingBatchRequest(
            tenant_id=tenant.id,
            document_id=document.id,
            document_version_id=version.id,
            retrieval_index_version_id=index_version.id,
            batch_index=0,
            batch_size=10,
        ),
        embedding_model=embedding_model,
        neo4j_client=neo4j_client,
        opensearch_client=opensearch_client,
    )
    await complete_document_indexing(
        db_session,
        tenant_id=tenant.id,
        document_version_id=version.id,
        retrieval_index_version_id=index_version.id,
    )
    await db_session.flush()

    embeddings = list(
        await db_session.scalars(select(ChunkEmbedding).order_by(ChunkEmbedding.chunk_id))
    )
    await db_session.refresh(coverage)

    assert plan.batch_count == 1
    assert result.embedded_count == 2
    assert result.vector_count == 2
    assert result.lexical_count == 2
    assert [embedding.chunk_id for embedding in embeddings] == [
        "chunk-000001",
        "chunk-000002",
    ]
    assert embeddings[0].vector == [1.0, 1.0, 1.0, 1.0]
    assert len(embedding_model.requests) == 1
    assert len(neo4j_client.calls) == 1
    assert "Acme Corporation" in opensearch_client.bulk_bodies[0]
    assert coverage.status == DocumentIndexCoverageStatus.COMPLETED
    assert coverage.chunk_count == 2
    assert coverage.embedded_count == 2
    assert coverage.vector_count == 2
    assert coverage.lexical_count == 2

    second = await index_document_version_batch(
        db_session,
        IndexingBatchRequest(
            tenant_id=tenant.id,
            document_id=document.id,
            document_version_id=version.id,
            retrieval_index_version_id=index_version.id,
            batch_index=0,
            batch_size=10,
        ),
        embedding_model=embedding_model,
        neo4j_client=neo4j_client,
        opensearch_client=opensearch_client,
    )
    duplicate_count = await db_session.scalar(select(ChunkEmbedding))

    assert second.embedded_count == 2
    assert duplicate_count is not None
    assert len(list(await db_session.scalars(select(ChunkEmbedding)))) == 2


async def test_failed_document_indexing_records_bounded_error(
    db_session: AsyncSession,
) -> None:
    tenant, document, version, index_version = await _seed_indexable_document(db_session)
    await begin_document_indexing(
        db_session,
        tenant_id=tenant.id,
        document_id=document.id,
        document_version_id=version.id,
        retrieval_index_version_id=index_version.id,
        chunk_count=2,
    )

    coverage = await fail_document_indexing(
        db_session,
        tenant_id=tenant.id,
        document_version_id=version.id,
        retrieval_index_version_id=index_version.id,
        error_code="indexing_failed",
        error_message="x" * 1000,
    )

    assert coverage.status == DocumentIndexCoverageStatus.FAILED
    assert coverage.error_code == "indexing_failed"
    assert coverage.error_message == "x" * 500
