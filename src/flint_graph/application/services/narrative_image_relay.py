"""Opt-in image dispatch and recovery; never consumes other outbox topics."""

from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flint_graph.application.narrative_image_workflow import (
    CANCELLED_TOPIC,
    QUEUED_TOPIC,
    ImageJobPayload,
    validate_image_payload,
)
from flint_graph.application.services.narrative_images import (
    abandon_image_job,
    register_image_workflow,
)
from flint_graph.domain.enums import OutboxMessageStatus
from flint_graph.infrastructure.db.models import NarrativeImageJob, OutboxMessage


class ImageDispatcher(Protocol):
    async def start(self, payload: ImageJobPayload) -> UUID: ...

    async def cancel(self, payload: ImageJobPayload, *, run_id: UUID) -> None: ...

    async def closed(self, payload: ImageJobPayload, *, run_id: UUID) -> bool: ...


async def relay_image_message(
    session: AsyncSession,
    *,
    dispatcher: ImageDispatcher,
    retry_delay_seconds: int = 30,
) -> bool | None:
    """Caller commits the acknowledgement and run registration together.

    A lost commit replays the same Temporal run (USE_EXISTING); a per-message
    savepoint keeps one bad record from starving independent jobs.
    """
    if not 1 <= retry_delay_seconds <= 3600:
        raise ValueError("Invalid image relay limits")
    message = await session.scalar(
        select(OutboxMessage)
        .where(
            OutboxMessage.status == OutboxMessageStatus.PENDING,
            OutboxMessage.topic.in_([QUEUED_TOPIC, CANCELLED_TOPIC]),
            OutboxMessage.available_at <= datetime.now(UTC),
        )
        .order_by(
            case((OutboxMessage.topic == QUEUED_TOPIC, 0), else_=1),
            OutboxMessage.available_at,
            OutboxMessage.created_at,
            OutboxMessage.id,
        )
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if message is None:
        return None
    message_id = message.id
    try:
        async with session.begin_nested():
            payload = validate_image_payload(message.payload)
            job_id, tenant_id = UUID(payload["job_id"]), UUID(payload["tenant_id"])
            if (
                message.aggregate_type != "narrative_image_job"
                or message.aggregate_id != job_id
                or message.tenant_id != tenant_id
            ):
                raise ValueError("Invalid image dispatch identity")
            job = await session.scalar(
                select(NarrativeImageJob)
                .where(NarrativeImageJob.id == job_id, NarrativeImageJob.tenant_id == tenant_id)
                .execution_options(populate_existing=True)
            )
            if job is None:
                raise ValueError("Invalid image dispatch identity")
            if job.status in ("queued", "running"):
                if message.topic == QUEUED_TOPIC:
                    run_id = await dispatcher.start(payload)
                    await register_image_workflow(
                        session, tenant_id=tenant_id, job_id=job_id, workflow_run_id=run_id
                    )
                else:
                    if job.workflow_run_id is None:
                        raise ValueError("Image dispatch registration pending")
                    await dispatcher.cancel(payload, run_id=job.workflow_run_id)
            # Terminal jobs need no workflow start or cancellation.
            message.status = OutboxMessageStatus.PUBLISHED
            message.published_at = datetime.now(UTC)
            message.last_error = None
            message.locked_by = message.locked_at = None
            await session.flush()
        return True
    except Exception:
        failed = await session.get(OutboxMessage, message_id, populate_existing=True)
        if failed is None:
            return False
        failed.attempt_count += 1
        failed.available_at = datetime.now(UTC) + timedelta(seconds=retry_delay_seconds)
        failed.last_error = "dispatch_unavailable"
        failed.locked_by = failed.locked_at = None
        await session.flush()
    return False


async def relay_image_batch(
    factory: async_sessionmaker[AsyncSession],
    *,
    dispatcher: ImageDispatcher,
    batch_size: int = 10,
    retry_delay_seconds: int = 30,
) -> int:
    """Commit each registration before issuing the next message's RPC."""
    if not 1 <= batch_size <= 100:
        raise ValueError("Invalid image relay limits")
    published = 0
    for _ in range(batch_size):
        async with factory() as session:
            result = await relay_image_message(
                session, dispatcher=dispatcher, retry_delay_seconds=retry_delay_seconds
            )
            await session.commit()
        if result is None:
            break
        published += int(result)
    return published


async def recover_stale_image_jobs(
    factory: async_sessionmaker[AsyncSession],
    *,
    dispatcher: ImageDispatcher,
    older_than: timedelta = timedelta(minutes=30),
    limit: int = 20,
) -> int:
    """Fail active jobs whose registered run has closed without finishing them.

    A job is closed only after its own run is observed closed, so a slow but live
    generation is never interrupted by recovery.
    """
    cutoff = datetime.now(UTC) - older_than
    age = func.coalesce(NarrativeImageJob.started_at, NarrativeImageJob.created_at)
    async with factory() as session:
        candidates = list(
            await session.execute(
                select(
                    NarrativeImageJob.id,
                    NarrativeImageJob.tenant_id,
                    NarrativeImageJob.workflow_run_id,
                )
                .where(
                    NarrativeImageJob.status.in_(("queued", "running")),
                    NarrativeImageJob.workflow_run_id.is_not(None),
                    age < cutoff,
                )
                .order_by(age, NarrativeImageJob.id)
                .limit(limit)
            )
        )
    recovered = 0
    for job_id, tenant_id, run_id in candidates:
        payload = ImageJobPayload(schema_version="1", tenant_id=str(tenant_id), job_id=str(job_id))
        try:
            if not await dispatcher.closed(payload, run_id=run_id):
                continue
        except Exception:
            continue
        async with factory() as session:
            closed = await abandon_image_job(
                session, job_id=job_id, workflow_run_id=run_id, error_code="worker_interrupted"
            )
            await session.commit()
        recovered += int(closed is not None)
    return recovered
