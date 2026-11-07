"""Opt-in music dispatch and recovery (ADR 0067); never consumes other outbox topics."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flint_graph.application.narrative_image_workflow import (
    MUSIC_CANCELLED_TOPIC,
    MUSIC_QUEUED_TOPIC,
    ImageJobPayload,
    validate_image_payload,
)
from flint_graph.application.services.narrative_image_relay import ImageDispatcher
from flint_graph.application.services.narrative_music import (
    abandon_music_job,
    register_music_workflow,
)
from flint_graph.domain.enums import OutboxMessageStatus
from flint_graph.infrastructure.db.models import NarrativeMusicJob, OutboxMessage


async def relay_music_message(
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
        raise ValueError("Invalid music relay limits")
    message = await session.scalar(
        select(OutboxMessage)
        .where(
            OutboxMessage.status == OutboxMessageStatus.PENDING,
            OutboxMessage.topic.in_([MUSIC_QUEUED_TOPIC, MUSIC_CANCELLED_TOPIC]),
            OutboxMessage.available_at <= datetime.now(UTC),
        )
        .order_by(
            case((OutboxMessage.topic == MUSIC_QUEUED_TOPIC, 0), else_=1),
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
                message.aggregate_type != "narrative_music_job"
                or message.aggregate_id != job_id
                or message.tenant_id != tenant_id
            ):
                raise ValueError("Invalid music dispatch identity")
            job = await session.scalar(
                select(NarrativeMusicJob)
                .where(NarrativeMusicJob.id == job_id, NarrativeMusicJob.tenant_id == tenant_id)
                .execution_options(populate_existing=True)
            )
            if job is None:
                raise ValueError("Invalid music dispatch identity")
            if job.status in ("queued", "running"):
                if message.topic == MUSIC_QUEUED_TOPIC:
                    run_id = await dispatcher.start(payload)
                    await register_music_workflow(
                        session, tenant_id=tenant_id, job_id=job_id, workflow_run_id=run_id
                    )
                else:
                    if job.workflow_run_id is None:
                        raise ValueError("Music dispatch registration pending")
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


async def relay_music_batch(
    factory: async_sessionmaker[AsyncSession],
    *,
    dispatcher: ImageDispatcher,
    batch_size: int = 10,
    retry_delay_seconds: int = 30,
) -> int:
    """Commit each registration before issuing the next message's RPC."""
    if not 1 <= batch_size <= 100:
        raise ValueError("Invalid music relay limits")
    published = 0
    for _ in range(batch_size):
        async with factory() as session:
            result = await relay_music_message(
                session, dispatcher=dispatcher, retry_delay_seconds=retry_delay_seconds
            )
            await session.commit()
        if result is None:
            break
        published += int(result)
    return published


async def recover_stale_music_jobs(
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
    age = func.coalesce(NarrativeMusicJob.started_at, NarrativeMusicJob.created_at)
    async with factory() as session:
        candidates = list(
            await session.execute(
                select(
                    NarrativeMusicJob.id,
                    NarrativeMusicJob.tenant_id,
                    NarrativeMusicJob.workflow_run_id,
                )
                .where(
                    NarrativeMusicJob.status.in_(("queued", "running")),
                    NarrativeMusicJob.workflow_run_id.is_not(None),
                    age < cutoff,
                )
                .order_by(age, NarrativeMusicJob.id)
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
            closed = await abandon_music_job(
                session, job_id=job_id, workflow_run_id=run_id, error_code="worker_interrupted"
            )
            await session.commit()
        recovered += int(closed is not None)
    return recovered
