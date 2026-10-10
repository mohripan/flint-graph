from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.outbox_contracts import (
    INGESTION_JOB_AGGREGATE_TYPE,
    INGESTION_JOB_CANCELLED_TOPIC,
    IngestionJobCancelledPayload,
)
from flint_graph.application.services.ingestion_jobs import JobRecord
from flint_graph.application.services.job_transitions import transition_ingestion_job
from flint_graph.application.services.outbox import append_outbox_message, capture_trace_context
from flint_graph.domain.enums import IngestionJobStatus
from flint_graph.domain.errors import NotFoundError
from flint_graph.infrastructure.db.models import DocumentVersion, IngestionJob, OutboxMessage


async def cancel_ingestion_job(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    job_id: UUID,
) -> JobRecord:
    row = (
        await session.execute(
            select(IngestionJob, DocumentVersion.version_number)
            .join(DocumentVersion, DocumentVersion.id == IngestionJob.document_version_id)
            .where(IngestionJob.id == job_id, IngestionJob.tenant_id == tenant_id)
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError(f"Ingestion job '{job_id}' was not found.")

    job, version_number = row
    job = await transition_ingestion_job(
        session,
        tenant_id=tenant_id,
        job_id=job_id,
        target_status=IngestionJobStatus.CANCELLED,
        event_type="job.cancelled",
        details={"requested_by": "api"},
        expected_current_statuses={
            IngestionJobStatus.QUEUED,
            IngestionJobStatus.RUNNING,
        },
    )
    existing_dispatch = await session.scalar(select(OutboxMessage.id).where(
        OutboxMessage.tenant_id == tenant_id,
        OutboxMessage.topic == INGESTION_JOB_CANCELLED_TOPIC,
        OutboxMessage.aggregate_id == job.id,
    ))
    if existing_dispatch is not None:
        return JobRecord(job=job, version_number=version_number, created=False)
    trace_context = capture_trace_context()
    payload = IngestionJobCancelledPayload(
        tenant_id=str(tenant_id),
        document_id=str(job.document_id),
        document_version_id=str(job.document_version_id),
        ingestion_job_id=str(job.id),
        idempotency_key=job.idempotency_key,
        trace_context=trace_context,
    )
    await append_outbox_message(
        session,
        tenant_id=tenant_id,
        topic=INGESTION_JOB_CANCELLED_TOPIC,
        aggregate_type=INGESTION_JOB_AGGREGATE_TYPE,
        aggregate_id=job.id,
        payload=dict(payload),
        headers=trace_context,
    )
    return JobRecord(job=job, version_number=version_number, created=False)
