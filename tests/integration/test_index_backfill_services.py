from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.embeddings import (
    EmbeddingBatchRequest,
    EmbeddingBatchResult,
    EmbeddingModel,
    EmbeddingVector,
)
from flint_graph.application.services.index_backfill import (
    complete_backfill_document,
    create_index_backfill_job,
    fail_backfill_document,
    load_next_backfill_batch,
    mark_backfill_running,
)
from flint_graph.application.services.indexing import (
    IndexingBatchRequest,
    begin_document_indexing,
    complete_document_indexing,
    index_document_version_batch,
    plan_document_indexing,
    reconcile_completed_index_projections,
    reconcile_document_index_projection,
)
from flint_graph.application.services.retrieval_index_versions import (
    RetrievalIndexVersionSpec,
    activate_retrieval_index_version,
    create_retrieval_index_version,
)
from flint_graph.domain.enums import (
    DocumentVersionStatus,
    IndexBackfillJobStatus,
    RetrievalIndexScope,
    SourceType,
)
from flint_graph.infrastructure.db.models import (
    ChunkEmbedding,
    Document,
    DocumentChunk,
    DocumentVersion,
    IndexBackfillJob,
    RetrievalIndexVersion,
    Tenant,
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
        self.created_indices: list[tuple[str, dict[str, Any]]] = []
        self.bulk_bodies: list[str] = []

    async def ensure_index(self, *, index_name: str, mapping: dict[str, Any]) -> None:
        self.created_indices.append((index_name, mapping))

    async def bulk(self, *, body: str) -> None:
        self.bulk_bodies.append(body)


class FakeEmbeddingModel(EmbeddingModel):
    async def embed_batch(self, request: EmbeddingBatchRequest) -> EmbeddingBatchResult:
        return EmbeddingBatchResult(
            provider=request.provider,
            model=request.model,
            dimensions=request.dimensions,
            embeddings=[
                EmbeddingVector(
                    input_id=item.input_id,
                    vector=[float(index + 1)] * request.dimensions,
                )
                for index, item in enumerate(request.inputs)
            ],
        )


async def _seed_backfill_fixture(
    session: AsyncSession,
) -> tuple[Tenant, list[Document], list[DocumentVersion], RetrievalIndexVersion]:
    tenant = Tenant(name="backfill-services")
    other_tenant = Tenant(name="backfill-services-other")
    session.add_all([tenant, other_tenant])
    await session.flush()

    versions: list[DocumentVersion] = []
    documents: list[Document] = []
    for index, owner in enumerate([tenant, tenant, other_tenant], start=1):
        document = Document(
            tenant_id=owner.id,
            title=f"Backfill Doc {index}",
            source_type=SourceType.UPLOAD,
            next_version_number=2,
        )
        session.add(document)
        await session.flush()
        version = DocumentVersion(
            document_id=document.id,
            version_number=1,
            status=DocumentVersionStatus.ACTIVE,
            content_hash=f"sha256:document-{index}",
        )
        session.add(version)
        await session.flush()
        session.add(
            DocumentChunk(
                tenant_id=owner.id,
                document_id=document.id,
                document_version_id=version.id,
                chunk_id="chunk-000001",
                chunk_index=0,
                text=f"Backfill chunk {index}",
                chunk_hash=f"sha256:chunk-{index}",
            )
        )
        documents.append(document)
        versions.append(version)

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
            neo4j_vector_index_name="chunk_embedding_backfill",
            neo4j_vector_property_name="embedding",
            opensearch_index_name="flint_graph_chunks_backfill",
            opensearch_alias_name="flint_graph_chunks_active",
        ),
    )
    await activate_retrieval_index_version(session, version_id=index_version.id)
    await session.flush()
    return tenant, documents, versions, index_version


async def test_load_next_backfill_batch_scans_missing_and_stale_coverage(
    db_session: AsyncSession,
) -> None:
    tenant, documents, versions, index_version = await _seed_backfill_fixture(db_session)
    await begin_document_indexing(
        db_session,
        tenant_id=tenant.id,
        document_id=documents[0].id,
        document_version_id=versions[0].id,
        retrieval_index_version_id=index_version.id,
        chunk_count=1,
    )
    await complete_document_indexing(
        db_session,
        tenant_id=tenant.id,
        document_version_id=versions[0].id,
        retrieval_index_version_id=index_version.id,
    )
    db_session.add(
        ChunkEmbedding(
            tenant_id=tenant.id,
            document_id=documents[0].id,
            document_version_id=versions[0].id,
            retrieval_index_version_id=index_version.id,
            chunk_id="chunk-000001",
            chunk_hash="sha256:old-stale-hash",
            vector_dimension=4,
            vector=[0.1, 0.2, 0.3, 0.4],
            provider_metadata={},
            request_hash="sha256:request",
        )
    )
    job = await create_index_backfill_job(
        db_session,
        tenant_id=tenant.id,
        retrieval_index_version_id=index_version.id,
    )

    batch = await load_next_backfill_batch(db_session, job_id=job.id, batch_size=10)

    assert [item.document_version_id for item in batch.documents] == [
        versions[0].id,
        versions[1].id,
    ]
    assert batch.done is False
    assert job.total_count == 2


async def test_backfill_checkpoint_resumes_after_processed_document(
    db_session: AsyncSession,
) -> None:
    tenant, _documents, versions, index_version = await _seed_backfill_fixture(db_session)
    job = await create_index_backfill_job(
        db_session,
        tenant_id=tenant.id,
        retrieval_index_version_id=index_version.id,
    )
    first_batch = await load_next_backfill_batch(db_session, job_id=job.id, batch_size=1)
    first_document = first_batch.documents[0]

    await complete_backfill_document(
        db_session,
        job_id=job.id,
        document_version_id=first_document.document_version_id,
    )
    second_batch = await load_next_backfill_batch(db_session, job_id=job.id, batch_size=10)

    assert first_document.document_version_id == versions[0].id
    assert [item.document_version_id for item in second_batch.documents] == [versions[1].id]
    assert job.processed_count == 1
    assert job.checkpoint == {"after_document_version_id": str(versions[0].id)}


async def test_scoped_backfill_limits_to_document_version(
    db_session: AsyncSession,
) -> None:
    tenant, _documents, versions, index_version = await _seed_backfill_fixture(db_session)
    job = await create_index_backfill_job(
        db_session,
        tenant_id=tenant.id,
        retrieval_index_version_id=index_version.id,
        document_version_id=versions[1].id,
    )

    batch = await load_next_backfill_batch(db_session, job_id=job.id, batch_size=10)

    assert [item.document_version_id for item in batch.documents] == [versions[1].id]
    assert job.total_count == 1


async def test_failed_backfill_document_updates_counters_and_bounded_error(
    db_session: AsyncSession,
) -> None:
    tenant, _documents, versions, index_version = await _seed_backfill_fixture(db_session)
    job = await create_index_backfill_job(
        db_session,
        tenant_id=tenant.id,
        retrieval_index_version_id=index_version.id,
    )

    await fail_backfill_document(
        db_session,
        job_id=job.id,
        document_version_id=versions[0].id,
        error_code="indexing_failed",
        error_message="x" * 1000,
    )

    assert job.failed_count == 1
    assert job.last_error == {
        "document_version_id": str(versions[0].id),
        "code": "indexing_failed",
        "message": "x" * 500,
    }
    assert job.checkpoint == {"after_document_version_id": str(versions[0].id)}


async def test_mark_backfill_running_preserves_existing_progress(
    db_session: AsyncSession,
) -> None:
    tenant, _documents, versions, index_version = await _seed_backfill_fixture(db_session)
    job = IndexBackfillJob(
        tenant_id=tenant.id,
        retrieval_index_version_id=index_version.id,
        status=IndexBackfillJobStatus.FAILED,
        total_count=2,
        processed_count=1,
        failed_count=1,
        checkpoint={"after_document_version_id": str(versions[0].id)},
        last_error={"code": "previous"},
    )
    db_session.add(job)
    await db_session.flush()

    await mark_backfill_running(db_session, job_id=job.id)

    assert job.status == IndexBackfillJobStatus.RUNNING
    assert job.processed_count == 1
    assert job.failed_count == 1
    assert job.checkpoint == {"after_document_version_id": str(versions[0].id)}


async def test_reconcile_document_index_projection_replays_from_stored_embeddings(
    db_session: AsyncSession,
) -> None:
    tenant, documents, versions, index_version = await _seed_backfill_fixture(db_session)
    embedding_model = FakeEmbeddingModel()
    neo4j_client = FakeNeo4jClient()
    opensearch_client = FakeOpenSearchClient()
    await plan_document_indexing(
        db_session,
        tenant_id=tenant.id,
        document_id=documents[0].id,
        document_version_id=versions[0].id,
        retrieval_index_version_id=index_version.id,
        batch_size=10,
    )
    await index_document_version_batch(
        db_session,
        IndexingBatchRequest(
            tenant_id=tenant.id,
            document_id=documents[0].id,
            document_version_id=versions[0].id,
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
        document_version_id=versions[0].id,
        retrieval_index_version_id=index_version.id,
    )
    neo4j_client.calls.clear()
    opensearch_client.bulk_bodies.clear()

    result = await reconcile_document_index_projection(
        db_session,
        tenant_id=tenant.id,
        document_version_id=versions[0].id,
        retrieval_index_version_id=index_version.id,
        neo4j_client=neo4j_client,
        opensearch_client=opensearch_client,
    )

    assert result.vector_count == 1
    assert result.lexical_count == 1
    assert len(neo4j_client.calls) == 1
    assert "Backfill chunk 1" in opensearch_client.bulk_bodies[0]


async def test_reconcile_document_index_projection_requires_current_embeddings(
    db_session: AsyncSession,
) -> None:
    tenant, _documents, versions, index_version = await _seed_backfill_fixture(db_session)

    try:
        await reconcile_document_index_projection(
            db_session,
            tenant_id=tenant.id,
            document_version_id=versions[0].id,
            retrieval_index_version_id=index_version.id,
            neo4j_client=FakeNeo4jClient(),
            opensearch_client=FakeOpenSearchClient(),
        )
    except RuntimeError as exc:
        assert str(exc) == "missing current chunk embeddings for document version"
    else:
        raise AssertionError("missing embeddings should fail reconcile")


async def test_reconcile_completed_index_projections_scans_completed_coverage(
    db_session: AsyncSession,
) -> None:
    tenant, documents, versions, index_version = await _seed_backfill_fixture(db_session)
    embedding_model = FakeEmbeddingModel()
    initial_neo4j = FakeNeo4jClient()
    initial_opensearch = FakeOpenSearchClient()
    await plan_document_indexing(
        db_session,
        tenant_id=tenant.id,
        document_id=documents[0].id,
        document_version_id=versions[0].id,
        retrieval_index_version_id=index_version.id,
        batch_size=10,
    )
    await index_document_version_batch(
        db_session,
        IndexingBatchRequest(
            tenant_id=tenant.id,
            document_id=documents[0].id,
            document_version_id=versions[0].id,
            retrieval_index_version_id=index_version.id,
            batch_index=0,
            batch_size=10,
        ),
        embedding_model=embedding_model,
        neo4j_client=initial_neo4j,
        opensearch_client=initial_opensearch,
    )
    await complete_document_indexing(
        db_session,
        tenant_id=tenant.id,
        document_version_id=versions[0].id,
        retrieval_index_version_id=index_version.id,
    )

    neo4j_client = FakeNeo4jClient()
    opensearch_client = FakeOpenSearchClient()
    count = await reconcile_completed_index_projections(
        db_session,
        neo4j_client=neo4j_client,
        opensearch_client=opensearch_client,
    )

    assert count == 1
    assert len(neo4j_client.calls) == 1
    assert len(opensearch_client.bulk_bodies) == 1
