from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from temporalio import activity

from atlas_rag.application.outbox_contracts import (
    IngestionFailurePayload,
    IngestionJobQueuedPayload,
)
from atlas_rag.application.services.job_transitions import transition_ingestion_job
from atlas_rag.domain.enums import IngestionJobStatus
from atlas_rag.infrastructure.db.session import SessionFactory
from atlas_rag.workflows.ingestion import (
    MARK_JOB_COMPLETED_ACTIVITY,
    MARK_JOB_FAILED_ACTIVITY,
    MARK_JOB_RUNNING_ACTIVITY,
    RUN_STUB_INGESTION_ACTIVITY,
)


def _tenant_id(payload: IngestionJobQueuedPayload) -> UUID:
    return UUID(payload["tenant_id"])


def _job_id(payload: IngestionJobQueuedPayload) -> UUID:
    return UUID(payload["ingestion_job_id"])


async def mark_ingestion_job_running_for_payload(
    session: AsyncSession,
    payload: IngestionJobQueuedPayload,
) -> None:
    await transition_ingestion_job(
        session,
        tenant_id=_tenant_id(payload),
        job_id=_job_id(payload),
        target_status=IngestionJobStatus.RUNNING,
        event_type="job.started",
        details={"worker": "temporal"},
        expected_current_statuses={IngestionJobStatus.QUEUED},
    )


async def mark_ingestion_job_completed_for_payload(
    session: AsyncSession,
    payload: IngestionJobQueuedPayload,
) -> None:
    await transition_ingestion_job(
        session,
        tenant_id=_tenant_id(payload),
        job_id=_job_id(payload),
        target_status=IngestionJobStatus.COMPLETED,
        event_type="job.completed",
        details={"mode": "stub"},
        expected_current_statuses={IngestionJobStatus.RUNNING},
    )


async def mark_ingestion_job_failed_for_payload(
    session: AsyncSession,
    failure: IngestionFailurePayload,
) -> None:
    payload = failure["payload"]
    await transition_ingestion_job(
        session,
        tenant_id=_tenant_id(payload),
        job_id=_job_id(payload),
        target_status=IngestionJobStatus.FAILED,
        event_type="job.failed",
        details={"mode": "stub"},
        error_code=failure["error_code"],
        error_message=failure["error_message"],
    )


@activity.defn(name=MARK_JOB_RUNNING_ACTIVITY)
async def mark_ingestion_job_running(payload: IngestionJobQueuedPayload) -> None:
    async with SessionFactory() as session:
        try:
            await mark_ingestion_job_running_for_payload(session, payload)
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@activity.defn(name=RUN_STUB_INGESTION_ACTIVITY)
async def run_stub_ingestion(payload: IngestionJobQueuedPayload) -> None:
    if payload["source_uri"] == "atlas://fail-stub-ingestion":
        raise RuntimeError("stub ingestion failed")


@activity.defn(name=MARK_JOB_COMPLETED_ACTIVITY)
async def mark_ingestion_job_completed(payload: IngestionJobQueuedPayload) -> None:
    async with SessionFactory() as session:
        try:
            await mark_ingestion_job_completed_for_payload(session, payload)
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@activity.defn(name=MARK_JOB_FAILED_ACTIVITY)
async def mark_ingestion_job_failed(failure: IngestionFailurePayload) -> None:
    async with SessionFactory() as session:
        try:
            await mark_ingestion_job_failed_for_payload(session, failure)
            await session.commit()
        except Exception:
            await session.rollback()
            raise
