from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.services.document_versions import (
    activate_document_version,
    cancel_document_version,
    fail_document_version,
)
from atlas_rag.application.services.documents import create_document
from atlas_rag.application.services.ingestion_jobs import create_ingestion_job
from atlas_rag.application.services.job_cancellation import cancel_ingestion_job
from atlas_rag.application.services.job_transitions import transition_ingestion_job
from atlas_rag.application.services.tenants import create_tenant
from atlas_rag.domain.enums import DocumentVersionStatus, IngestionJobStatus, SourceType
from atlas_rag.infrastructure.db.models import DocumentVersion


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
