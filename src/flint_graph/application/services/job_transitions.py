from collections.abc import Collection
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.document_versions import (
    activate_document_version,
    cancel_document_version,
    fail_document_version,
)
from flint_graph.domain.enums import IngestionJobStatus
from flint_graph.domain.errors import ConflictError, NotFoundError
from flint_graph.domain.transitions import can_transition_job
from flint_graph.infrastructure.db.models import Document, IngestionJob, IngestionJobEvent
from flint_graph.observability import metrics
from flint_graph.observability.instruments import INGESTION_JOB_TRANSITIONS

_TERMINAL_STATUSES = {
    IngestionJobStatus.COMPLETED,
    IngestionJobStatus.FAILED,
    IngestionJobStatus.CANCELLED,
}


async def transition_ingestion_job(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    job_id: UUID,
    target_status: IngestionJobStatus,
    event_type: str,
    details: dict[str, Any],
    expected_current_statuses: Collection[IngestionJobStatus] | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> IngestionJob:
    # Serialize all lifecycle mutations on the owning document first. Deletion
    # already locks Document before versions; job-first locking deadlocks with it.
    document = await session.scalar(
        select(Document)
        .join(IngestionJob, IngestionJob.document_id == Document.id)
        .where(IngestionJob.id == job_id, IngestionJob.tenant_id == tenant_id,
               Document.tenant_id == tenant_id)
        .with_for_update(of=Document)
        .execution_options(populate_existing=True)
    )
    if document is None:
        raise NotFoundError(f"Ingestion job '{job_id}' was not found.")
    job = await session.scalar(
        select(IngestionJob)
        .where(IngestionJob.id == job_id, IngestionJob.tenant_id == tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None:
        raise NotFoundError(f"Ingestion job '{job_id}' was not found.")

    current_status = job.status
    if document.deleted_at is not None:
        if current_status == IngestionJobStatus.CANCELLED:
            # A late worker notification cannot overturn the deletion outcome.
            return job
        if current_status not in _TERMINAL_STATUSES:
            target_status = IngestionJobStatus.CANCELLED
            event_type = "job.cancelled"
            details = {**details, "reason": "document_deleted"}
            expected_current_statuses = {IngestionJobStatus.QUEUED, IngestionJobStatus.RUNNING}
    if current_status == target_status:
        return job

    if expected_current_statuses is not None and current_status not in expected_current_statuses:
        raise ConflictError(
            f"Cannot transition ingestion job '{job_id}' from "
            f"'{current_status}' to '{target_status}'."
        )

    if not can_transition_job(current_status, target_status):
        raise ConflictError(
            f"Cannot transition ingestion job '{job_id}' from "
            f"'{current_status}' to '{target_status}'."
        )

    now = datetime.now(UTC)
    job.status = target_status
    if target_status == IngestionJobStatus.RUNNING and job.started_at is None:
        job.started_at = now
    if target_status in _TERMINAL_STATUSES and job.completed_at is None:
        job.completed_at = now
    if target_status == IngestionJobStatus.FAILED:
        job.error_code = error_code
        job.error_message = error_message

    if document.deleted_at is not None:
        # The document/version tombstone is authoritative. Settle the job without
        # attempting DELETED -> FAILED/CANCELLED/ACTIVE version transitions.
        pass
    elif target_status == IngestionJobStatus.COMPLETED:
        await activate_document_version(
            session,
            tenant_id=tenant_id,
            version_id=job.document_version_id,
        )
    elif target_status == IngestionJobStatus.FAILED:
        await fail_document_version(
            session,
            tenant_id=tenant_id,
            version_id=job.document_version_id,
        )
    elif target_status == IngestionJobStatus.CANCELLED:
        await cancel_document_version(
            session,
            tenant_id=tenant_id,
            version_id=job.document_version_id,
        )

    session.add(
        IngestionJobEvent(
            job_id=job.id,
            event_type=event_type,
            from_status=current_status,
            to_status=target_status,
            details=details,
            created_at=now,
        )
    )
    await session.flush()
    metrics.add(
        INGESTION_JOB_TRANSITIONS,
        **{"flint_graph.job.status": target_status.value},
    )
    return job
