import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.retrieval_index_versions import (
    RetrievalIndexVersionSpec,
    activate_retrieval_index_version,
    create_retrieval_index_version,
    fail_retrieval_index_version,
)
from flint_graph.domain.enums import (
    DocumentVersionStatus,
    IndexBackfillJobStatus,
    RetrievalIndexScope,
    RetrievalIndexVersionStatus,
    SourceType,
)
from flint_graph.domain.errors import ConflictError, NotFoundError
from flint_graph.infrastructure.db.models import (
    ChunkEmbedding,
    Document,
    DocumentChunk,
    DocumentVersion,
    IndexBackfillJob,
    RetrievalIndexVersion,
    Tenant,
)


async def _seed_document(
    session: AsyncSession,
    *,
    tenant_name: str = "retrieval-ledger",
) -> tuple[Tenant, Document, DocumentVersion, DocumentChunk]:
    tenant = Tenant(name=tenant_name)
    session.add(tenant)
    await session.flush()

    document = Document(
        tenant_id=tenant.id,
        title="Retrieval Doc",
        source_type=SourceType.UPLOAD,
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

    chunk = DocumentChunk(
        tenant_id=tenant.id,
        document_id=document.id,
        document_version_id=version.id,
        chunk_id="chunk-000001",
        chunk_index=0,
        text="Acme Corporation is headquartered in Berlin.",
        chunk_hash="sha256:chunk",
    )
    session.add(chunk)
    await session.flush()
    return tenant, document, version, chunk


def _spec(*, model: str = "deterministic-test", dimensions: int = 4) -> RetrievalIndexVersionSpec:
    return RetrievalIndexVersionSpec(
        embedding_provider="deterministic",
        embedding_model=model,
        vector_dimension=dimensions,
        embedding_config_hash=f"sha256:{model}:{dimensions}",
        chunking_schema_version="1",
        chunking_config_hash="sha256:chunking",
        lexical_schema_version="1",
        neo4j_vector_index_name=f"flint_graph_chunks_{dimensions}",
        neo4j_vector_property_name=f"embedding_v{dimensions}",
        opensearch_index_name=f"flint_graph_chunks_v{dimensions:06d}",
        opensearch_alias_name="flint_graph_chunks_active",
        metadata={"phase": 2},
    )


async def test_activate_retrieval_index_version_deprecates_only_same_scope(
    db_session: AsyncSession,
) -> None:
    tenant_a, _document, _version, _chunk = await _seed_document(
        db_session,
        tenant_name="tenant-a",
    )
    tenant_b, _document_b, _version_b, _chunk_b = await _seed_document(
        db_session,
        tenant_name="tenant-b",
    )

    first_global = await create_retrieval_index_version(
        db_session,
        scope=RetrievalIndexScope.GLOBAL,
        spec=_spec(model="global-v1"),
    )
    second_global = await create_retrieval_index_version(
        db_session,
        scope=RetrievalIndexScope.GLOBAL,
        spec=_spec(model="global-v2"),
    )
    tenant_a_version = await create_retrieval_index_version(
        db_session,
        scope=RetrievalIndexScope.TENANT,
        tenant_id=tenant_a.id,
        spec=_spec(model="tenant-a-v1"),
    )
    tenant_b_version = await create_retrieval_index_version(
        db_session,
        scope=RetrievalIndexScope.TENANT,
        tenant_id=tenant_b.id,
        spec=_spec(model="tenant-b-v1"),
    )

    await activate_retrieval_index_version(db_session, version_id=first_global.id)
    await activate_retrieval_index_version(db_session, version_id=tenant_a_version.id)
    await activate_retrieval_index_version(db_session, version_id=tenant_b_version.id)
    await activate_retrieval_index_version(db_session, version_id=second_global.id)
    await db_session.commit()

    statuses = {
        version.embedding_model: version.status
        for version in (
            await db_session.execute(select(RetrievalIndexVersion))
        ).scalars()
    }
    assert statuses["global-v1"] == RetrievalIndexVersionStatus.DEPRECATED
    assert statuses["global-v2"] == RetrievalIndexVersionStatus.ACTIVE
    assert statuses["tenant-a-v1"] == RetrievalIndexVersionStatus.ACTIVE
    assert statuses["tenant-b-v1"] == RetrievalIndexVersionStatus.ACTIVE


async def test_retrieval_index_version_service_validates_scope_and_transitions(
    db_session: AsyncSession,
) -> None:
    tenant, _document, _version, _chunk = await _seed_document(db_session)

    with pytest.raises(ConflictError, match="tenant_id is required"):
        await create_retrieval_index_version(
            db_session,
            scope=RetrievalIndexScope.TENANT,
            spec=_spec(),
        )

    with pytest.raises(ConflictError, match="tenant_id must be empty"):
        await create_retrieval_index_version(
            db_session,
            scope=RetrievalIndexScope.GLOBAL,
            tenant_id=tenant.id,
            spec=_spec(),
        )

    version = await create_retrieval_index_version(
        db_session,
        scope=RetrievalIndexScope.TENANT,
        tenant_id=tenant.id,
        spec=_spec(model="tenant-fail"),
    )
    await fail_retrieval_index_version(
        db_session,
        version_id=version.id,
        error_code="provider_error",
        error_message="embedding provider failed",
    )

    with pytest.raises(ConflictError, match="failed"):
        await activate_retrieval_index_version(db_session, version_id=version.id)

    with pytest.raises(NotFoundError):
        await activate_retrieval_index_version(db_session, version_id=tenant.id)


async def test_chunk_embedding_idempotency_uses_index_version_chunk_identity_and_hash(
    db_session: AsyncSession,
) -> None:
    tenant, document, version, chunk = await _seed_document(db_session)
    index_version = await create_retrieval_index_version(
        db_session,
        scope=RetrievalIndexScope.TENANT,
        tenant_id=tenant.id,
        spec=_spec(),
    )
    await db_session.flush()

    embedding = ChunkEmbedding(
        tenant_id=tenant.id,
        document_id=document.id,
        document_version_id=version.id,
        retrieval_index_version_id=index_version.id,
        chunk_id=chunk.chunk_id,
        chunk_hash=chunk.chunk_hash,
        vector_dimension=4,
        vector=[0.1, 0.2, 0.3, 0.4],
        provider_metadata={"source": "test"},
        request_hash="sha256:request",
    )
    duplicate = ChunkEmbedding(
        tenant_id=tenant.id,
        document_id=document.id,
        document_version_id=version.id,
        retrieval_index_version_id=index_version.id,
        chunk_id=chunk.chunk_id,
        chunk_hash=chunk.chunk_hash,
        vector_dimension=4,
        vector=[0.1, 0.2, 0.3, 0.4],
        provider_metadata={"source": "test"},
        request_hash="sha256:request",
    )

    db_session.add_all([embedding, duplicate])
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_index_backfill_job_persists_scope_progress_and_checkpoint(
    db_session: AsyncSession,
) -> None:
    tenant, document, version, _chunk = await _seed_document(db_session)
    index_version = await create_retrieval_index_version(
        db_session,
        scope=RetrievalIndexScope.TENANT,
        tenant_id=tenant.id,
        spec=_spec(),
    )
    await db_session.flush()

    job = IndexBackfillJob(
        tenant_id=tenant.id,
        retrieval_index_version_id=index_version.id,
        document_id=document.id,
        document_version_id=version.id,
        status=IndexBackfillJobStatus.RUNNING,
        total_count=12,
        processed_count=5,
        failed_count=1,
        checkpoint={"after_document_version_id": str(version.id)},
        last_error={"code": "projection_error"},
    )
    db_session.add(job)
    await db_session.commit()

    reloaded = (await db_session.execute(select(IndexBackfillJob))).scalar_one()
    assert reloaded.tenant_id == tenant.id
    assert reloaded.retrieval_index_version_id == index_version.id
    assert reloaded.checkpoint == {"after_document_version_id": str(version.id)}
    assert reloaded.last_error == {"code": "projection_error"}
