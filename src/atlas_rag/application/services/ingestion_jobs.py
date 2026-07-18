from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.outbox_contracts import (
    INGESTION_JOB_AGGREGATE_TYPE,
    INGESTION_JOB_QUEUED_TOPIC,
    IngestionJobQueuedPayload,
)
from atlas_rag.application.services.outbox import append_outbox_message, capture_trace_context
from atlas_rag.domain.enums import DocumentVersionStatus, IngestionJobStatus
from atlas_rag.domain.errors import ConflictError, NotFoundError
from atlas_rag.infrastructure.db.models import (
    Document,
    DocumentVersion,
    IngestionJob,
    IngestionJobEvent,
)


@dataclass(slots=True)
class JobRecord:
    job: IngestionJob
    version_number: int
    created: bool


async def _find_by_idempotency_key(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    idempotency_key: str,
) -> tuple[IngestionJob, int] | None:
    row = (
        await session.execute(
            select(IngestionJob, DocumentVersion.version_number)
            .join(DocumentVersion, DocumentVersion.id == IngestionJob.document_version_id)
            .where(
                IngestionJob.tenant_id == tenant_id,
                IngestionJob.idempotency_key == idempotency_key,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    return row[0], row[1]


async def create_ingestion_job(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    idempotency_key: str,
) -> JobRecord:
    try:
        async with session.begin_nested():
            existing = await _find_by_idempotency_key(
                session,
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                job, version_number = existing
                if job.document_id != document_id:
                    raise ConflictError(
                        "This idempotency key was already used for a different document."
                    )
                return JobRecord(job=job, version_number=version_number, created=False)

            document = await session.scalar(
                select(Document)
                .where(Document.id == document_id, Document.tenant_id == tenant_id)
                .with_for_update()
            )
            if document is None:
                raise NotFoundError(f"Document '{document_id}' was not found.")
            if document.deleted_at is not None:
                raise ConflictError("Cannot create an ingestion job for a deleted document.")

            version_number = document.next_version_number
            document.next_version_number += 1

            version = DocumentVersion(
                document_id=document.id,
                version_number=version_number,
                status=DocumentVersionStatus.PENDING,
            )
            session.add(version)
            await session.flush()

            job = IngestionJob(
                tenant_id=tenant_id,
                document_id=document.id,
                document_version_id=version.id,
                status=IngestionJobStatus.QUEUED,
                idempotency_key=idempotency_key,
            )
            session.add(job)
            await session.flush()

            session.add(
                IngestionJobEvent(
                    job_id=job.id,
                    event_type="job.queued",
                    from_status=None,
                    to_status=IngestionJobStatus.QUEUED,
                    details={"document_version": version_number},
                    created_at=datetime.now(UTC),
                )
            )
            await session.flush()

            trace_context = capture_trace_context()
            payload = IngestionJobQueuedPayload(
                tenant_id=str(tenant_id),
                document_id=str(document.id),
                document_version_id=str(version.id),
                ingestion_job_id=str(job.id),
                idempotency_key=idempotency_key,
                source_type=document.source_type.value,
                source_uri=document.source_uri,
                trace_context=trace_context,
            )
            await append_outbox_message(
                session,
                tenant_id=tenant_id,
                topic=INGESTION_JOB_QUEUED_TOPIC,
                aggregate_type=INGESTION_JOB_AGGREGATE_TYPE,
                aggregate_id=job.id,
                payload=dict(payload),
                headers=trace_context,
            )
    except IntegrityError as exc:
        existing = await _find_by_idempotency_key(
            session,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
        )
        if existing is None:
            raise
        job, version_number = existing
        if job.document_id != document_id:
            raise ConflictError(
                "This idempotency key was already used for a different document."
            ) from exc
        return JobRecord(job=job, version_number=version_number, created=False)

    await session.refresh(job)
    return JobRecord(job=job, version_number=version_number, created=True)


async def get_ingestion_job(
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
    return JobRecord(job=row[0], version_number=row[1], created=False)


async def list_ingestion_job_events(
    session: AsyncSession, *, tenant_id: UUID, job_id: UUID
) -> list[IngestionJobEvent]:
    exists = await session.scalar(
        select(IngestionJob.id).where(
            IngestionJob.id == job_id,
            IngestionJob.tenant_id == tenant_id,
        )
    )
    if exists is None:
        raise NotFoundError(f"Ingestion job '{job_id}' was not found.")

    result = await session.scalars(
        select(IngestionJobEvent)
        .where(IngestionJobEvent.job_id == job_id)
        .order_by(
            IngestionJobEvent.created_at,
            case(
                (IngestionJobEvent.to_status == IngestionJobStatus.QUEUED, 0),
                (IngestionJobEvent.to_status == IngestionJobStatus.RUNNING, 1),
                else_=2,
            ),
            IngestionJobEvent.id,
        )
    )
    return list(result)
