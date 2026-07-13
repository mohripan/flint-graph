from collections.abc import Collection
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.services.document_versions import (
    activate_document_version,
    cancel_document_version,
    fail_document_version,
)
from atlas_rag.domain.enums import IngestionJobStatus
from atlas_rag.domain.errors import ConflictError, NotFoundError
from atlas_rag.domain.transitions import can_transition_job
from atlas_rag.infrastructure.db.models import IngestionJob, IngestionJobEvent

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
    job = await session.scalar(
        select(IngestionJob)
        .where(IngestionJob.id == job_id, IngestionJob.tenant_id == tenant_id)
        .with_for_update()
    )
    if job is None:
        raise NotFoundError(f"Ingestion job '{job_id}' was not found.")

    current_status = job.status
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

    if target_status == IngestionJobStatus.COMPLETED:
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
    return job
