from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.services.documents import create_document
from atlas_rag.application.services.ingestion_jobs import create_ingestion_job
from atlas_rag.application.services.job_transitions import transition_ingestion_job
from atlas_rag.application.services.tenants import create_tenant
from atlas_rag.domain.enums import IngestionJobStatus, SourceType
from atlas_rag.domain.errors import ConflictError, NotFoundError
from atlas_rag.infrastructure.db.models import IngestionJobEvent


async def _create_queued_job(db_session: AsyncSession) -> tuple[UUID, UUID]:
    tenant = await create_tenant(db_session, name="Transition Tenant")
    document = await create_document(
        db_session,
        tenant_id=tenant.id,
        title="Transition Document",
        source_type=SourceType.URL,
        source_uri="https://example.test/transitions",
        external_id="transition-document",
    )
    record = await create_ingestion_job(
        db_session,
        tenant_id=tenant.id,
        document_id=document.id,
        idempotency_key="transition-job",
    )
    return tenant.id, record.job.id


async def test_transition_service_moves_job_to_running_and_appends_event(
    db_session: AsyncSession,
) -> None:
    tenant_id, job_id = await _create_queued_job(db_session)

    job = await transition_ingestion_job(
        db_session,
        tenant_id=tenant_id,
        job_id=job_id,
        target_status=IngestionJobStatus.RUNNING,
        event_type="job.started",
        details={"worker": "test-worker"},
    )

    events = list(
        await db_session.scalars(
            select(IngestionJobEvent).where(IngestionJobEvent.job_id == job.id)
        )
    )

    assert job.status == IngestionJobStatus.RUNNING
    assert job.started_at is not None
    assert [event.event_type for event in events] == ["job.queued", "job.started"]
    assert events[-1].from_status == IngestionJobStatus.QUEUED
    assert events[-1].to_status == IngestionJobStatus.RUNNING
    assert events[-1].details == {"worker": "test-worker"}


async def test_repeated_same_transition_is_idempotent(
    db_session: AsyncSession,
) -> None:
    tenant_id, job_id = await _create_queued_job(db_session)

    await transition_ingestion_job(
        db_session,
        tenant_id=tenant_id,
        job_id=job_id,
        target_status=IngestionJobStatus.RUNNING,
        event_type="job.started",
        details={"attempt": 1},
    )
    job = await transition_ingestion_job(
        db_session,
        tenant_id=tenant_id,
        job_id=job_id,
        target_status=IngestionJobStatus.RUNNING,
        event_type="job.started",
        details={"attempt": 1},
    )

    events = list(
        await db_session.scalars(
            select(IngestionJobEvent).where(IngestionJobEvent.job_id == job.id)
        )
    )

    assert job.status == IngestionJobStatus.RUNNING
    assert [event.event_type for event in events] == ["job.queued", "job.started"]


async def test_invalid_transition_is_rejected(
    db_session: AsyncSession,
) -> None:
    tenant_id, job_id = await _create_queued_job(db_session)
    await transition_ingestion_job(
        db_session,
        tenant_id=tenant_id,
        job_id=job_id,
        target_status=IngestionJobStatus.RUNNING,
        event_type="job.started",
        details={},
    )
    await transition_ingestion_job(
        db_session,
        tenant_id=tenant_id,
        job_id=job_id,
        target_status=IngestionJobStatus.COMPLETED,
        event_type="job.completed",
        details={},
    )

    with pytest.raises(ConflictError):
        await transition_ingestion_job(
            db_session,
            tenant_id=tenant_id,
            job_id=job_id,
            target_status=IngestionJobStatus.RUNNING,
            event_type="job.started",
            details={},
        )


async def test_failed_transition_sets_terminal_error_fields(
    db_session: AsyncSession,
) -> None:
    tenant_id, job_id = await _create_queued_job(db_session)

    job = await transition_ingestion_job(
        db_session,
        tenant_id=tenant_id,
        job_id=job_id,
        target_status=IngestionJobStatus.FAILED,
        event_type="job.failed",
        details={"stage": "dispatch"},
        error_code="dispatch_error",
        error_message="Temporal was unavailable.",
    )

    assert job.status == IngestionJobStatus.FAILED
    assert job.completed_at is not None
    assert job.error_code == "dispatch_error"
    assert job.error_message == "Temporal was unavailable."


async def test_transition_service_preserves_tenant_boundary(
    db_session: AsyncSession,
) -> None:
    _, job_id = await _create_queued_job(db_session)
    other_tenant = await create_tenant(db_session, name="Other Transition Tenant")

    with pytest.raises(NotFoundError):
        await transition_ingestion_job(
            db_session,
            tenant_id=other_tenant.id,
            job_id=job_id,
            target_status=IngestionJobStatus.RUNNING,
            event_type="job.started",
            details={},
        )
