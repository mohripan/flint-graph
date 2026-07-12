from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.outbox_contracts import IngestionJobQueuedPayload
from atlas_rag.application.services.documents import create_document
from atlas_rag.application.services.ingestion_jobs import create_ingestion_job
from atlas_rag.application.services.tenants import create_tenant
from atlas_rag.domain.enums import IngestionJobStatus, SourceType
from atlas_rag.infrastructure.db.models import IngestionJob, IngestionJobEvent
from atlas_rag.worker.activities.ingestion import (
    mark_ingestion_job_completed_for_payload,
    mark_ingestion_job_failed_for_payload,
    mark_ingestion_job_running_for_payload,
)


async def _create_payload(
    db_session: AsyncSession,
    *,
    idempotency_key: str = "activity-job",
) -> IngestionJobQueuedPayload:
    tenant = await create_tenant(db_session, name=f"Activity Tenant {idempotency_key}")
    document = await create_document(
        db_session,
        tenant_id=tenant.id,
        title="Activity Document",
        source_type=SourceType.URL,
        source_uri="https://example.test/activity",
        external_id=f"activity-document-{idempotency_key}",
    )
    record = await create_ingestion_job(
        db_session,
        tenant_id=tenant.id,
        document_id=document.id,
        idempotency_key=idempotency_key,
    )
    return {
        "tenant_id": str(tenant.id),
        "document_id": str(document.id),
        "document_version_id": str(record.job.document_version_id),
        "ingestion_job_id": str(record.job.id),
        "idempotency_key": idempotency_key,
        "source_type": document.source_type.value,
        "source_uri": document.source_uri,
        "trace_context": {},
    }


async def test_ingestion_activity_helpers_mark_job_completed(
    db_session: AsyncSession,
) -> None:
    payload = await _create_payload(db_session)

    await mark_ingestion_job_running_for_payload(db_session, payload)
    await mark_ingestion_job_completed_for_payload(db_session, payload)

    job = await db_session.get(IngestionJob, UUID(payload["ingestion_job_id"]))
    assert job is not None
    events = list(
        await db_session.scalars(
            select(IngestionJobEvent).where(IngestionJobEvent.job_id == job.id)
        )
    )

    assert job.status == IngestionJobStatus.COMPLETED
    assert job.started_at is not None
    assert job.completed_at is not None
    assert [event.event_type for event in events] == [
        "job.queued",
        "job.started",
        "job.completed",
    ]


async def test_ingestion_activity_helpers_mark_job_failed(
    db_session: AsyncSession,
) -> None:
    payload = await _create_payload(db_session, idempotency_key="activity-failed-job")

    await mark_ingestion_job_running_for_payload(db_session, payload)
    await mark_ingestion_job_failed_for_payload(
        db_session,
        {
            "payload": payload,
            "error_code": "ingestion_failed",
            "error_message": "stub ingestion failed",
        },
    )

    job = await db_session.get(IngestionJob, UUID(payload["ingestion_job_id"]))
    assert job is not None

    assert job.status == IngestionJobStatus.FAILED
    assert job.completed_at is not None
    assert job.error_code == "ingestion_failed"
    assert job.error_message == "stub ingestion failed"
