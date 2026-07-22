from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.document_lifecycle import (
    delete_document,
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
)
from flint_graph.application.services.ingestion_jobs import create_ingestion_job
from flint_graph.application.services.job_cancellation import cancel_ingestion_job
from flint_graph.application.services.job_transitions import transition_ingestion_job
from flint_graph.application.services.retrieval_index_versions import (
    RetrievalIndexVersionSpec,
    activate_retrieval_index_version,
    create_retrieval_index_version,
)
from flint_graph.application.services.tenants import create_tenant
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
)


class CapturingCypherClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def execute(
        self, query: str, parameters: dict[str, object] | None = None
    ) -> list[dict[str, object]]:
        self.calls.append((query, parameters or {}))
        return []


class CapturingOpenSearchBulkClient:
    def __init__(self) -> None:
        self.bulk_bodies: list[str] = []

    async def bulk(self, *, body: str) -> None:
        self.bulk_bodies.append(body)


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
