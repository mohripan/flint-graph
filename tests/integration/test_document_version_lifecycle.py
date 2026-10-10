import asyncio
import os
from dataclasses import replace
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.document_lifecycle import (
    delete_document,
    retry_projection_cleanups,
    run_projection_cleanup,
)
from flint_graph.application.services.document_versions import (
    activate_document_version,
    cancel_document_version,
    fail_document_version,
)
from flint_graph.application.services.documents import create_document
from flint_graph.application.services.indexing import (
    begin_document_indexing,
    complete_document_indexing,
    reconcile_completed_index_projections,
    reconcile_document_index_projection,
)
from flint_graph.application.services.ingestion_jobs import create_ingestion_job
from flint_graph.application.services.job_cancellation import cancel_ingestion_job
from flint_graph.application.services.job_transitions import transition_ingestion_job
from flint_graph.application.services.lexical_projection import (
    LexicalChunkRecord,
    opensearch_chunk_document_id,
)
from flint_graph.application.services.retrieval_index_versions import (
    RetrievalIndexVersionSpec,
    activate_retrieval_index_version,
    create_retrieval_index_version,
)
from flint_graph.application.services.tenants import create_tenant
from flint_graph.application.services.vector_projection import (
    VectorChunkRecord,
    project_chunk_vectors,
)
from flint_graph.config import Settings
from flint_graph.domain.enums import (
    DocumentIndexCoverageStatus,
    DocumentLifecycleEventType,
    DocumentProjectionCleanupStatus,
    DocumentVersionStatus,
    IngestionJobStatus,
    RetrievalIndexScope,
    SourceType,
)
from flint_graph.domain.errors import ConflictError
from flint_graph.infrastructure.db.models import (
    Document,
    DocumentChunk,
    DocumentIndexCoverage,
    DocumentLifecycleEvent,
    DocumentProjectionCleanup,
    DocumentVersion,
    IngestionJob,
    IngestionJobEvent,
    OutboxMessage,
    RetrievalIndexVersion,
)
from flint_graph.infrastructure.neo4j import create_neo4j_client
from flint_graph.infrastructure.opensearch import (
    OpenSearchClient,
    build_chunk_index_mapping,
    build_upsert_chunks_bulk_body,
)


class CapturingCypherClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def execute(
        self, query: str, parameters: dict[str, object] | None = None
    ) -> list[dict[str, object]]:
        self.calls.append((query, parameters or {}))
        return []


@pytest.mark.parametrize("initial", [IngestionJobStatus.QUEUED, IngestionJobStatus.RUNNING])
@pytest.mark.parametrize("late", [IngestionJobStatus.COMPLETED, IngestionJobStatus.FAILED])
@pytest.mark.parametrize("autoflush", [True, False])
async def test_delete_settles_inflight_job_and_ignores_late_worker_outcome(
    extraction_db_session: AsyncSession,
    initial: IngestionJobStatus,
    late: IngestionJobStatus,
    autoflush: bool,
) -> None:
    session = extraction_db_session
    session.autoflush = autoflush
    tenant_id, version_ids = await _create_document_with_jobs(
        session,
        tenant_name="Deletion race tenant",
        document_external_id="deletion-race",
        job_keys=["deletion-race-job"],
    )
    job = await session.scalar(select(IngestionJob))
    assert job is not None
    if initial == IngestionJobStatus.RUNNING:
        await transition_ingestion_job(
            session,
            tenant_id=tenant_id,
            job_id=job.id,
            target_status=initial,
            event_type="job.started",
            details={},
        )
    await delete_document(session, tenant_id=tenant_id, document_id=job.document_id)
    await session.commit()
    await session.refresh(job)
    assert job.status == IngestionJobStatus.CANCELLED
    assert job.completed_at is not None
    await transition_ingestion_job(
        session,
        tenant_id=tenant_id,
        job_id=job.id,
        target_status=late,
        event_type=f"job.{late.value}",
        details={},
    )
    await delete_document(session, tenant_id=tenant_id, document_id=job.document_id)
    await cancel_ingestion_job(session, tenant_id=tenant_id, job_id=job.id)
    await session.commit()
    version = await session.get(DocumentVersion, version_ids[0])
    assert version is not None and version.status == DocumentVersionStatus.DELETED
    assert job.status == IngestionJobStatus.CANCELLED
    events = list(
        await session.scalars(
            select(IngestionJobEvent).where(
                IngestionJobEvent.job_id == job.id,
                IngestionJobEvent.event_type == "job.cancelled",
            )
        )
    )
    messages = list(
        await session.scalars(
            select(OutboxMessage).where(
                OutboxMessage.aggregate_id == job.id,
                OutboxMessage.topic == "ingestion.job_cancelled",
            )
        )
    )
    assert len(events) == len(messages) == 1


@pytest.mark.parametrize("late", [IngestionJobStatus.COMPLETED, IngestionJobStatus.FAILED])
async def test_postgres_delete_and_stale_worker_sessions_serialize_without_deadlock(
    extraction_db_session: AsyncSession,
    late: IngestionJobStatus,
) -> None:
    session = extraction_db_session
    assert session.bind is not None
    if session.bind.dialect.name != "postgresql":
        pytest.skip("Row-lock and stale-session proof requires real PostgreSQL.")
    tenant_id, _ = await _create_document_with_jobs(
        session,
        tenant_name="Concurrent deletion tenant",
        document_external_id="concurrent-delete",
        job_keys=["concurrent-delete-job"],
    )
    job = await session.scalar(select(IngestionJob))
    assert job is not None
    await transition_ingestion_job(
        session,
        tenant_id=tenant_id,
        job_id=job.id,
        target_status=IngestionJobStatus.RUNNING,
        event_type="job.started",
        details={},
    )
    await session.commit()
    locked = asyncio.Event()
    attempted = asyncio.Event()
    async with AsyncSession(bind=session.bind, expire_on_commit=False) as worker:
        stale_job = await worker.get(IngestionJob, job.id)
        assert stale_job is not None and stale_job.status == IngestionJobStatus.RUNNING
        await worker.commit()

        async def deleting() -> None:
            await session.execute(text("SET LOCAL lock_timeout = '2s'"))
            await delete_document(session, tenant_id=tenant_id, document_id=job.document_id)
            locked.set()
            await attempted.wait()
            await session.commit()

        async def notifying() -> None:
            await locked.wait()
            await worker.execute(text("SET LOCAL lock_timeout = '2s'"))
            attempted.set()
            outcome = await transition_ingestion_job(
                worker,
                tenant_id=tenant_id,
                job_id=job.id,
                target_status=late,
                event_type=f"job.{late.value}",
                details={"worker": "late"},
            )
            assert outcome.status == IngestionJobStatus.CANCELLED
            await worker.commit()

        await asyncio.wait_for(asyncio.gather(deleting(), notifying()), timeout=5)
        assert stale_job.status == IngestionJobStatus.CANCELLED


class CapturingOpenSearchBulkClient:
    def __init__(self) -> None:
        self.bulk_bodies: list[str] = []

    async def bulk(self, *, body: str) -> None:
        self.bulk_bodies.append(body)


@pytest.mark.skipif(
    not os.getenv("FLINT_GRAPH_LIVE_PROJECTION_INTEGRATION"),
    reason="Opt-in synthetic live PostgreSQL/Neo4j/OpenSearch lifecycle test.",
)
@pytest.mark.parametrize("lifecycle", ["deleted", "superseded"])
async def test_partial_projection_cleanup_live(
    extraction_db_session: AsyncSession,
    lifecycle: str,
) -> None:
    session = extraction_db_session
    if session.get_bind().dialect.name != "postgresql":
        pytest.skip("Live verification uses an isolated PostgreSQL schema.")
    session.autoflush = False
    tenant_id, versions = await _create_document_with_jobs(
        session,
        tenant_name="Disposable live cleanup",
        document_external_id="live-cleanup",
        job_keys=["live-v1", "live-v2"],
    )
    await activate_document_version(session, tenant_id=tenant_id, version_id=versions[0])
    version = await session.get(DocumentVersion, versions[0])
    assert version is not None
    index_id = await _create_active_index_coverage(
        session, tenant_id=tenant_id, version=version, chunk_count=0
    )
    index = await session.get(RetrievalIndexVersion, index_id)
    assert index is not None
    physical_index_name = f"flintgraph-cleanup-verification-{uuid4().hex}"
    index.opensearch_index_name = physical_index_name
    coverage = await session.scalar(
        select(DocumentIndexCoverage).where(
            DocumentIndexCoverage.document_version_id == version.id,
        )
    )
    assert coverage is not None
    coverage.status = DocumentIndexCoverageStatus.RUNNING
    for number in range(2):
        session.add(
            DocumentChunk(
                tenant_id=tenant_id,
                document_id=version.document_id,
                document_version_id=version.id,
                chunk_id=f"live-{number}",
                chunk_index=number,
                text="Synthetic cleanup record",
                chunk_hash=f"live-{number}",
                metadata_={},
            )
        )
    await session.commit()
    foreign_tenant, other_index = uuid4(), uuid4()
    vector = VectorChunkRecord(
        tenant_id=tenant_id,
        document_id=version.document_id,
        document_version_id=version.id,
        chunk_id="live-0",
        chunk_hash="live-0",
        retrieval_index_version_id=index_id,
        vector=[1.0, 0.0, 0.0, 0.0],
    )
    lexical = LexicalChunkRecord(
        tenant_id=tenant_id,
        document_id=version.document_id,
        document_version_id=version.id,
        chunk_id="live-0",
        chunk_hash="live-0",
        title="Disposable",
        text="Synthetic cleanup record",
        heading_path=[],
        page_start=None,
        page_end=None,
        source_uri=None,
        metadata={},
    )
    foreign_lexical = replace(lexical, tenant_id=foreign_tenant)
    neo4j = create_neo4j_client(Settings(env="test"))
    async with httpx.AsyncClient(base_url="http://localhost:9200", timeout=30) as http:
        search = OpenSearchClient(http_client=http)
        await search.create_index(
            index_name=index.opensearch_index_name, mapping=build_chunk_index_mapping()
        )
        try:
            # Only one of two chunks exists externally, and PG counters are zero.
            await project_chunk_vectors(
                neo4j,
                records=[
                    vector,
                    replace(vector, tenant_id=foreign_tenant),
                    replace(vector, retrieval_index_version_id=other_index),
                ],
                vector_property_name="live_cleanup_embedding",
            )
            await search.bulk(
                body=build_upsert_chunks_bulk_body(
                    index_name=index.opensearch_index_name,
                    records=[lexical, foreign_lexical],
                    index_version_id=index_id,
                )
            )
            if lifecycle == "deleted":
                await delete_document(session, tenant_id=tenant_id, document_id=version.document_id)
            else:
                await activate_document_version(
                    session, tenant_id=tenant_id, version_id=versions[1]
                )
            await session.commit()
            cleanup = await session.scalar(
                select(DocumentProjectionCleanup).where(
                    DocumentProjectionCleanup.document_version_id == version.id,
                )
            )
            assert cleanup is not None
            result = await run_projection_cleanup(
                session, cleanup_id=cleanup.id, neo4j_client=neo4j, opensearch_client=search
            )
            assert result.status == DocumentProjectionCleanupStatus.COMPLETED
            assert result.chunk_count == result.vector_count == result.lexical_count == 2
            await session.commit()
            rows = await neo4j.execute(
                "MATCH (c:Chunk {document_version_id: $version}) RETURN c.tenant_id AS tenant, "
                "c.retrieval_index_version_id AS idx",
                {"version": str(version.id)},
            )
            assert {(row["tenant"], row["idx"]) for row in rows} == {
                (str(foreign_tenant), str(index_id)),
                (str(tenant_id), str(other_index)),
            }
            target = f"/{index.opensearch_index_name}/_doc/{opensearch_chunk_document_id(lexical)}"
            foreign = (
                f"/{index.opensearch_index_name}/_doc/"
                f"{opensearch_chunk_document_id(foreign_lexical)}"
            )
            assert (await http.get(target)).status_code == 404
            assert (await http.get(foreign)).status_code == 200
            with pytest.raises(ConflictError):
                await reconcile_document_index_projection(
                    session,
                    tenant_id=tenant_id,
                    document_version_id=version.id,
                    retrieval_index_version_id=index_id,
                    neo4j_client=neo4j,
                    opensearch_client=search,
                )
            await session.rollback()
            assert (await http.get(target)).status_code == 404
        finally:
            # Targets are UUID-scoped synthetic version/index identities only.
            await neo4j.execute(
                "MATCH (c:Chunk {document_version_id: $version}) DETACH DELETE c",
                {"version": str(versions[0])},
            )
            assert physical_index_name.startswith("flintgraph-cleanup-verification-")
            response = await http.delete(f"/{physical_index_name}")
            response.raise_for_status()
            await neo4j.close()


@pytest.mark.parametrize("status", list(DocumentIndexCoverageStatus))
@pytest.mark.parametrize("lifecycle", ["deleted", "superseded"])
async def test_partial_coverage_cleanup_uses_all_chunks_and_retries(
    extraction_db_session: AsyncSession,
    status: DocumentIndexCoverageStatus,
    lifecycle: str,
) -> None:
    session = extraction_db_session
    session.autoflush = False
    tenant_id, versions = await _create_document_with_jobs(
        session,
        tenant_name="Partial cleanup",
        document_external_id="partial-cleanup",
        job_keys=["partial-v1", "partial-v2"],
    )
    await activate_document_version(session, tenant_id=tenant_id, version_id=versions[0])
    version = await session.get(DocumentVersion, versions[0])
    assert version is not None
    index_id = await _create_active_index_coverage(
        session, tenant_id=tenant_id, version=version, chunk_count=0
    )
    coverage = await session.scalar(
        select(DocumentIndexCoverage).where(
            DocumentIndexCoverage.document_version_id == version.id,
        )
    )
    assert coverage is not None
    coverage.status = status
    # Projection counts can be zero even after a partial external write.
    for number in range(2):
        session.add(
            DocumentChunk(
                tenant_id=tenant_id,
                document_id=version.document_id,
                document_version_id=version.id,
                chunk_id=f"partial-{number}",
                chunk_index=number,
                text="Synthetic partial projection",
                chunk_hash=f"partial-{number}",
                metadata_={},
            )
        )
    await session.flush()
    if lifecycle == "deleted":
        await delete_document(session, tenant_id=tenant_id, document_id=version.document_id)
        await delete_document(session, tenant_id=tenant_id, document_id=version.document_id)
    else:
        await activate_document_version(session, tenant_id=tenant_id, version_id=versions[1])
        await activate_document_version(session, tenant_id=tenant_id, version_id=versions[1])
    await session.commit()
    cleanups = list(
        await session.scalars(
            select(DocumentProjectionCleanup).where(
                DocumentProjectionCleanup.document_version_id == version.id,
            )
        )
    )
    assert len(cleanups) == 1
    cleanup = cleanups[0]
    assert cleanup.retrieval_index_version_id == index_id
    assert cleanup.tenant_id == tenant_id
    cypher = CapturingCypherClient()

    class OnceFailingBulk(CapturingOpenSearchBulkClient):
        async def bulk(self, *, body: str) -> None:
            await super().bulk(body=body)
            if len(self.bulk_bodies) == 1:
                raise ValueError("OpenSearch bulk failed (1/2 items unsuccessful).")

    search = OnceFailingBulk()
    failed = await run_projection_cleanup(
        session, cleanup_id=cleanup.id, neo4j_client=cypher, opensearch_client=search
    )
    assert failed.status == DocumentProjectionCleanupStatus.FAILED
    await retry_projection_cleanups(session, tenant_id=tenant_id, document_id=version.document_id)
    completed = await run_projection_cleanup(
        session, cleanup_id=cleanup.id, neo4j_client=cypher, opensearch_client=search
    )
    assert completed.status == DocumentProjectionCleanupStatus.COMPLETED
    assert completed.chunk_count == completed.vector_count == completed.lexical_count == 2
    assert completed.attempt_count == 2
    assert search.bulk_bodies[0] == search.bulk_bodies[1]
    assert all(f"partial-{number}" in search.bulk_bodies[1] for number in range(2))
    assert str(versions[1]) not in search.bulk_bodies[1]
    calls = len(cypher.calls), len(search.bulk_bodies)
    await run_projection_cleanup(
        session, cleanup_id=cleanup.id, neo4j_client=cypher, opensearch_client=search
    )
    assert calls == (len(cypher.calls), len(search.bulk_bodies))
    await session.refresh(coverage)
    if status == DocumentIndexCoverageStatus.RUNNING:
        assert coverage.status == DocumentIndexCoverageStatus.CANCELLED


@pytest.mark.parametrize("lifecycle", ["deleted", "superseded"])
async def test_reconcile_cannot_recreate_stale_projection(
    extraction_db_session: AsyncSession,
    lifecycle: str,
) -> None:
    session = extraction_db_session
    tenant_id, versions = await _create_document_with_jobs(
        session,
        tenant_name="Stale reconcile",
        document_external_id="stale-reconcile",
        job_keys=["stale-v1", "stale-v2"],
    )
    await activate_document_version(session, tenant_id=tenant_id, version_id=versions[0])
    version = await session.get(DocumentVersion, versions[0])
    assert version is not None
    index_id = await _create_active_index_coverage(session, tenant_id=tenant_id, version=version)
    if lifecycle == "deleted":
        await delete_document(session, tenant_id=tenant_id, document_id=version.document_id)
    else:
        await activate_document_version(session, tenant_id=tenant_id, version_id=versions[1])
    cypher = CapturingCypherClient()
    search = CapturingOpenSearchBulkClient()
    with pytest.raises(ConflictError):
        await reconcile_document_index_projection(
            session,
            tenant_id=tenant_id,
            document_version_id=version.id,
            retrieval_index_version_id=index_id,
            neo4j_client=cypher,
            opensearch_client=search,
        )
    assert (
        await reconcile_completed_index_projections(
            session, tenant_id=tenant_id, neo4j_client=cypher, opensearch_client=search
        )
        == 0
    )
    assert not cypher.calls and not search.bulk_bodies


@pytest.mark.parametrize("lifecycle", ["deleted", "superseded"])
async def test_concurrent_reconcile_waits_for_lifecycle_and_refuses_replay(
    extraction_db_session: AsyncSession,
    lifecycle: str,
) -> None:
    session = extraction_db_session
    if session.get_bind().dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-lock concurrency verification.")
    tenant_id, versions = await _create_document_with_jobs(
        session,
        tenant_name="Replay race",
        document_external_id="replay-race",
        job_keys=["race-v1", "race-v2"],
    )
    await activate_document_version(session, tenant_id=tenant_id, version_id=versions[0])
    version = await session.get(DocumentVersion, versions[0])
    assert version is not None
    document_id = version.document_id
    index_id = await _create_active_index_coverage(session, tenant_id=tenant_id, version=version)
    await session.commit()
    async with AsyncSession(session.bind, expire_on_commit=False, autoflush=False) as worker:
        await worker.get(Document, document_id)  # Preloaded stale identity map.
        if lifecycle == "deleted":
            await delete_document(session, tenant_id=tenant_id, document_id=document_id)
        else:
            await activate_document_version(session, tenant_id=tenant_id, version_id=versions[1])
        attempted = asyncio.Event()
        cypher = CapturingCypherClient()
        search = CapturingOpenSearchBulkClient()

        async def replay() -> None:
            await worker.execute(text("SET LOCAL lock_timeout = '2s'"))
            attempted.set()
            with pytest.raises(ConflictError):
                await reconcile_document_index_projection(
                    worker,
                    tenant_id=tenant_id,
                    document_version_id=versions[0],
                    retrieval_index_version_id=index_id,
                    neo4j_client=cypher,
                    opensearch_client=search,
                )

        async def commit_lifecycle() -> None:
            await attempted.wait()
            await session.commit()

        await asyncio.wait_for(asyncio.gather(replay(), commit_lifecycle()), timeout=5)
        assert not cypher.calls and not search.bulk_bodies


async def _create_document_with_jobs(
    db_session: AsyncSession,
    *,
    tenant_name: str,
    document_external_id: str,
    job_keys: list[str],
) -> tuple[UUID, list[UUID]]:
    tenant = await create_tenant(db_session, name=tenant_name)
    document = await create_document(
        db_session,
        tenant_id=tenant.id,
        title=document_external_id,
        source_type=SourceType.UPLOAD,
        source_uri=None,
        external_id=document_external_id,
    )
    version_ids: list[UUID] = []
    for job_key in job_keys:
        record = await create_ingestion_job(
            db_session,
            tenant_id=tenant.id,
            document_id=document.id,
            idempotency_key=job_key,
        )
        version_ids.append(record.job.document_version_id)
    return tenant.id, version_ids


def _index_spec(model: str = "lifecycle-v1") -> RetrievalIndexVersionSpec:
    return RetrievalIndexVersionSpec(
        embedding_provider="deterministic",
        embedding_model=model,
        vector_dimension=4,
        embedding_config_hash=f"sha256:{model}",
        chunking_schema_version="1",
        chunking_config_hash="sha256:chunking",
        lexical_schema_version="1",
        neo4j_vector_index_name=f"flint_graph_chunks_{model.replace('-', '_')}",
        neo4j_vector_property_name="embedding_v000001",
        opensearch_index_name=f"flint_graph_chunks_{model.replace('-', '_')}",
        opensearch_alias_name="flint_graph_chunks_active",
        metadata={},
    )


async def _create_active_index_coverage(
    db_session: AsyncSession,
    *,
    tenant_id: UUID,
    version: DocumentVersion,
    chunk_count: int = 2,
) -> UUID:
    index_version = await create_retrieval_index_version(
        db_session,
        scope=RetrievalIndexScope.TENANT,
        tenant_id=tenant_id,
        spec=_index_spec(),
    )
    await activate_retrieval_index_version(db_session, version_id=index_version.id)
    db_session.add(
        DocumentIndexCoverage(
            tenant_id=tenant_id,
            document_id=version.document_id,
            document_version_id=version.id,
            retrieval_index_version_id=index_version.id,
            status=DocumentIndexCoverageStatus.COMPLETED,
            chunk_count=chunk_count,
            embedded_count=chunk_count,
            vector_count=chunk_count,
            lexical_count=chunk_count,
        )
    )
    await db_session.flush()
    return index_version.id


async def test_activating_new_version_supersedes_previous_active_version(
    db_session: AsyncSession,
) -> None:
    tenant_id, version_ids = await _create_document_with_jobs(
        db_session,
        tenant_name="Lifecycle Activate Tenant",
        document_external_id="lifecycle-activate",
        job_keys=["activate-v1", "activate-v2"],
    )

    await activate_document_version(db_session, tenant_id=tenant_id, version_id=version_ids[0])
    await activate_document_version(db_session, tenant_id=tenant_id, version_id=version_ids[1])

    first = await db_session.get(DocumentVersion, version_ids[0])
    second = await db_session.get(DocumentVersion, version_ids[1])
    assert first is not None
    assert second is not None
    assert first.status == DocumentVersionStatus.SUPERSEDED
    assert second.status == DocumentVersionStatus.ACTIVE


async def test_activating_replacement_creates_superseded_cleanup_work(
    db_session: AsyncSession,
) -> None:
    tenant_id, version_ids = await _create_document_with_jobs(
        db_session,
        tenant_name="Lifecycle Replacement Cleanup Tenant",
        document_external_id="lifecycle-replacement-cleanup",
        job_keys=["cleanup-v1", "cleanup-v2"],
    )
    await activate_document_version(db_session, tenant_id=tenant_id, version_id=version_ids[0])
    first = await db_session.get(DocumentVersion, version_ids[0])
    assert first is not None
    index_version_id = await _create_active_index_coverage(
        db_session,
        tenant_id=tenant_id,
        version=first,
        chunk_count=3,
    )

    await activate_document_version(db_session, tenant_id=tenant_id, version_id=version_ids[1])

    event = await db_session.scalar(
        select(DocumentLifecycleEvent).where(
            DocumentLifecycleEvent.tenant_id == tenant_id,
            DocumentLifecycleEvent.document_version_id == version_ids[0],
            DocumentLifecycleEvent.event_type == DocumentLifecycleEventType.VERSION_SUPERSEDED,
        )
    )
    cleanup = await db_session.scalar(
        select(DocumentProjectionCleanup).where(
            DocumentProjectionCleanup.tenant_id == tenant_id,
            DocumentProjectionCleanup.document_version_id == version_ids[0],
            DocumentProjectionCleanup.retrieval_index_version_id == index_version_id,
        )
    )
    assert event is not None
    assert cleanup is not None
    assert cleanup.status == DocumentProjectionCleanupStatus.PENDING
    assert cleanup.chunk_count == 3


async def test_deleting_document_marks_versions_deleted_and_creates_cleanup_work(
    db_session: AsyncSession,
) -> None:
    tenant_id, version_ids = await _create_document_with_jobs(
        db_session,
        tenant_name="Lifecycle Delete Cleanup Tenant",
        document_external_id="lifecycle-delete-cleanup",
        job_keys=["delete-v1"],
    )
    await activate_document_version(db_session, tenant_id=tenant_id, version_id=version_ids[0])
    version = await db_session.get(DocumentVersion, version_ids[0])
    assert version is not None
    index_version_id = await _create_active_index_coverage(
        db_session,
        tenant_id=tenant_id,
        version=version,
        chunk_count=4,
    )

    deleted = await delete_document(
        db_session,
        tenant_id=tenant_id,
        document_id=version.document_id,
        reason="user requested deletion",
    )

    assert deleted.document_id == version.document_id
    refreshed = await db_session.get(DocumentVersion, version_ids[0])
    assert refreshed is not None
    assert refreshed.status == DocumentVersionStatus.DELETED
    event = await db_session.scalar(
        select(DocumentLifecycleEvent).where(
            DocumentLifecycleEvent.tenant_id == tenant_id,
            DocumentLifecycleEvent.document_id == version.document_id,
            DocumentLifecycleEvent.event_type == DocumentLifecycleEventType.DOCUMENT_DELETED,
        )
    )
    cleanup = await db_session.scalar(
        select(DocumentProjectionCleanup).where(
            DocumentProjectionCleanup.tenant_id == tenant_id,
            DocumentProjectionCleanup.document_version_id == version_ids[0],
            DocumentProjectionCleanup.retrieval_index_version_id == index_version_id,
        )
    )
    assert event is not None
    assert event.reason == "user requested deletion"
    assert cleanup is not None
    assert cleanup.status == DocumentProjectionCleanupStatus.PENDING
    assert cleanup.stale_reason == "document_deleted"


async def test_deleting_document_marks_document_deleted_and_blocks_new_jobs(
    db_session: AsyncSession,
) -> None:
    tenant_id, version_ids = await _create_document_with_jobs(
        db_session,
        tenant_name="Lifecycle Tombstone Tenant",
        document_external_id="lifecycle-tombstone",
        job_keys=["tombstone-v1"],
    )
    version = await db_session.get(DocumentVersion, version_ids[0])
    assert version is not None

    await delete_document(
        db_session,
        tenant_id=tenant_id,
        document_id=version.document_id,
        reason="delete should be terminal",
    )

    document = await db_session.get(Document, version.document_id)
    assert document is not None
    assert document.deleted_at is not None
    try:
        await create_ingestion_job(
            db_session,
            tenant_id=tenant_id,
            document_id=version.document_id,
            idempotency_key="tombstone-v2",
        )
    except ConflictError:
        pass
    else:
        raise AssertionError("deleted documents must not accept new ingestion jobs")


async def test_indexing_begin_rejects_deleted_document_version(
    db_session: AsyncSession,
) -> None:
    tenant_id, version_ids = await _create_document_with_jobs(
        db_session,
        tenant_name="Lifecycle Index Begin Guard Tenant",
        document_external_id="lifecycle-index-begin-guard",
        job_keys=["index-begin-v1"],
    )
    version = await db_session.get(DocumentVersion, version_ids[0])
    assert version is not None
    index_version_id = await _create_active_index_coverage(
        db_session,
        tenant_id=tenant_id,
        version=version,
        chunk_count=0,
    )
    await delete_document(
        db_session,
        tenant_id=tenant_id,
        document_id=version.document_id,
        reason="index begin guard",
    )

    try:
        await begin_document_indexing(
            db_session,
            tenant_id=tenant_id,
            document_id=version.document_id,
            document_version_id=version.id,
            retrieval_index_version_id=index_version_id,
            chunk_count=0,
        )
    except ConflictError:
        pass
    else:
        raise AssertionError("deleted document versions must not begin indexing")


async def test_indexing_completion_does_not_resurrect_cancelled_deleted_coverage(
    db_session: AsyncSession,
) -> None:
    tenant_id, version_ids = await _create_document_with_jobs(
        db_session,
        tenant_name="Lifecycle Index Complete Guard Tenant",
        document_external_id="lifecycle-index-complete-guard",
        job_keys=["index-complete-v1"],
    )
    await activate_document_version(db_session, tenant_id=tenant_id, version_id=version_ids[0])
    version = await db_session.get(DocumentVersion, version_ids[0])
    assert version is not None
    index_version_id = await _create_active_index_coverage(
        db_session,
        tenant_id=tenant_id,
        version=version,
        chunk_count=0,
    )
    coverage = await db_session.scalar(
        select(DocumentIndexCoverage).where(
            DocumentIndexCoverage.document_version_id == version.id,
            DocumentIndexCoverage.retrieval_index_version_id == index_version_id,
        )
    )
    assert coverage is not None
    coverage.status = DocumentIndexCoverageStatus.RUNNING
    await db_session.flush()

    await delete_document(
        db_session,
        tenant_id=tenant_id,
        document_id=version.document_id,
        reason="index complete guard",
    )

    try:
        await complete_document_indexing(
            db_session,
            tenant_id=tenant_id,
            document_version_id=version.id,
            retrieval_index_version_id=index_version_id,
        )
    except ConflictError:
        pass
    else:
        raise AssertionError("late completion must not mark deleted coverage completed")
    await db_session.refresh(coverage)
    assert coverage.status == DocumentIndexCoverageStatus.CANCELLED


async def test_projection_cleanup_deletes_vector_and_lexical_records(
    db_session: AsyncSession,
) -> None:
    tenant_id, version_ids = await _create_document_with_jobs(
        db_session,
        tenant_name="Lifecycle Cleanup Execute Tenant",
        document_external_id="lifecycle-cleanup-execute",
        job_keys=["execute-v1"],
    )
    await activate_document_version(db_session, tenant_id=tenant_id, version_id=version_ids[0])
    version = await db_session.get(DocumentVersion, version_ids[0])
    assert version is not None
    db_session.add(
        DocumentChunk(
            tenant_id=tenant_id,
            document_id=version.document_id,
            document_version_id=version.id,
            chunk_id="chunk-000001",
            chunk_index=0,
            text="Acme cleanup text",
            chunk_hash="sha256:chunk-cleanup",
            metadata_={"source_type": "upload"},
        )
    )
    await _create_active_index_coverage(
        db_session,
        tenant_id=tenant_id,
        version=version,
        chunk_count=1,
    )
    await delete_document(
        db_session,
        tenant_id=tenant_id,
        document_id=version.document_id,
        reason="cleanup execution test",
    )
    cleanup = await db_session.scalar(
        select(DocumentProjectionCleanup).where(
            DocumentProjectionCleanup.document_version_id == version.id
        )
    )
    assert cleanup is not None
    cypher_client = CapturingCypherClient()
    opensearch_client = CapturingOpenSearchBulkClient()

    completed = await run_projection_cleanup(
        db_session,
        cleanup_id=cleanup.id,
        neo4j_client=cypher_client,
        opensearch_client=opensearch_client,
    )

    assert completed.status == DocumentProjectionCleanupStatus.COMPLETED
    assert completed.vector_count == 1
    assert completed.lexical_count == 1
    assert cypher_client.calls
    assert "chunk-000001" in str(cypher_client.calls[0][1]["ids"])
    assert opensearch_client.bulk_bodies
    assert '"delete"' in opensearch_client.bulk_bodies[0]
    assert "chunk-000001" in opensearch_client.bulk_bodies[0]


async def test_failing_newer_version_does_not_disturb_current_active_version(
    db_session: AsyncSession,
) -> None:
    tenant_id, version_ids = await _create_document_with_jobs(
        db_session,
        tenant_name="Lifecycle Fail Tenant",
        document_external_id="lifecycle-fail",
        job_keys=["fail-v1", "fail-v2"],
    )

    await activate_document_version(db_session, tenant_id=tenant_id, version_id=version_ids[0])
    await fail_document_version(db_session, tenant_id=tenant_id, version_id=version_ids[1])

    first = await db_session.get(DocumentVersion, version_ids[0])
    second = await db_session.get(DocumentVersion, version_ids[1])
    assert first is not None
    assert second is not None
    assert first.status == DocumentVersionStatus.ACTIVE
    assert second.status == DocumentVersionStatus.FAILED


async def test_cancelling_newer_version_does_not_disturb_current_active_version(
    db_session: AsyncSession,
) -> None:
    tenant_id, version_ids = await _create_document_with_jobs(
        db_session,
        tenant_name="Lifecycle Cancel Tenant",
        document_external_id="lifecycle-cancel",
        job_keys=["cancel-v1", "cancel-v2"],
    )

    await activate_document_version(db_session, tenant_id=tenant_id, version_id=version_ids[0])
    await cancel_document_version(db_session, tenant_id=tenant_id, version_id=version_ids[1])

    first = await db_session.get(DocumentVersion, version_ids[0])
    second = await db_session.get(DocumentVersion, version_ids[1])
    assert first is not None
    assert second is not None
    assert first.status == DocumentVersionStatus.ACTIVE
    assert second.status == DocumentVersionStatus.CANCELLED


async def test_completed_job_activates_document_version(
    db_session: AsyncSession,
) -> None:
    tenant_id, version_ids = await _create_document_with_jobs(
        db_session,
        tenant_name="Lifecycle Job Complete Tenant",
        document_external_id="lifecycle-job-complete",
        job_keys=["job-complete-v1"],
    )
    version = await db_session.get(DocumentVersion, version_ids[0])
    assert version is not None

    record = await create_ingestion_job(
        db_session,
        tenant_id=tenant_id,
        document_id=version.document_id,
        idempotency_key="job-complete-v2",
    )
    await transition_ingestion_job(
        db_session,
        tenant_id=tenant_id,
        job_id=record.job.id,
        target_status=IngestionJobStatus.RUNNING,
        event_type="job.started",
        details={},
    )
    await transition_ingestion_job(
        db_session,
        tenant_id=tenant_id,
        job_id=record.job.id,
        target_status=IngestionJobStatus.COMPLETED,
        event_type="job.completed",
        details={},
    )

    completed_version = await db_session.get(DocumentVersion, record.job.document_version_id)
    assert completed_version is not None
    assert completed_version.status == DocumentVersionStatus.ACTIVE


async def test_failed_job_fails_document_version(
    db_session: AsyncSession,
) -> None:
    tenant_id, version_ids = await _create_document_with_jobs(
        db_session,
        tenant_name="Lifecycle Job Fail Tenant",
        document_external_id="lifecycle-job-fail",
        job_keys=["job-fail-v1"],
    )
    version = await db_session.get(DocumentVersion, version_ids[0])
    assert version is not None
    record = await create_ingestion_job(
        db_session,
        tenant_id=tenant_id,
        document_id=version.document_id,
        idempotency_key="job-fail-v2",
    )

    await transition_ingestion_job(
        db_session,
        tenant_id=tenant_id,
        job_id=record.job.id,
        target_status=IngestionJobStatus.FAILED,
        event_type="job.failed",
        details={},
        error_code="parse_failed",
        error_message="parse failed",
    )

    failed_version = await db_session.get(DocumentVersion, record.job.document_version_id)
    assert failed_version is not None
    assert failed_version.status == DocumentVersionStatus.FAILED


async def test_cancelled_job_cancels_document_version(
    db_session: AsyncSession,
) -> None:
    tenant_id, version_ids = await _create_document_with_jobs(
        db_session,
        tenant_name="Lifecycle Job Cancel Tenant",
        document_external_id="lifecycle-job-cancel",
        job_keys=["job-cancel-v1"],
    )
    version = await db_session.get(DocumentVersion, version_ids[0])
    assert version is not None
    record = await create_ingestion_job(
        db_session,
        tenant_id=tenant_id,
        document_id=version.document_id,
        idempotency_key="job-cancel-v2",
    )

    await cancel_ingestion_job(db_session, tenant_id=tenant_id, job_id=record.job.id)

    cancelled_version = await db_session.get(DocumentVersion, record.job.document_version_id)
    assert cancelled_version is not None
    assert cancelled_version.status == DocumentVersionStatus.CANCELLED
