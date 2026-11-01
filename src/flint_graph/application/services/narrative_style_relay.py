"""Separate training topics, exact-run registration and closed-run recovery."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flint_graph.application.narrative_image_workflow import ImageJobPayload, validate_image_payload
from flint_graph.application.services.narrative_image_relay import ImageDispatcher
from flint_graph.application.services.narrative_styles import ACTIVE, CANCELLED, QUEUED
from flint_graph.domain.enums import OutboxMessageStatus
from flint_graph.infrastructure.db.models import OutboxMessage
from flint_graph.infrastructure.db.narrative_style_models import NarrativeStyleJob


async def relay_style_batch(
    factory: async_sessionmaker[AsyncSession],
    *,
    dispatcher: ImageDispatcher,
    older_than: timedelta = timedelta(minutes=2),
) -> int:
    count = 0
    for _ in range(10):
        async with factory() as session:
            message = await session.scalar(
                select(OutboxMessage)
                .where(
                    OutboxMessage.topic.in_((QUEUED, CANCELLED)),
                    OutboxMessage.status == OutboxMessageStatus.PENDING,
                    OutboxMessage.available_at <= datetime.now(UTC),
                )
                .order_by(OutboxMessage.created_at, OutboxMessage.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if message is None:
                break
            try:
                payload = validate_image_payload(message.payload)
                job = await session.get(NarrativeStyleJob, UUID(payload["job_id"]))
                if (
                    job is None
                    or job.tenant_id != message.tenant_id
                    or job.id != message.aggregate_id
                    or str(job.tenant_id) != payload["tenant_id"]
                    or message.aggregate_type != "narrative_style_job"
                ):
                    raise ValueError("dispatch_identity")
                if message.topic == QUEUED and job.status in ACTIVE:
                    run_id = await dispatcher.start(payload)
                    locked = await session.scalar(
                        select(NarrativeStyleJob)
                        .where(NarrativeStyleJob.id == job.id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                    assert locked is not None
                    if locked.workflow_run_id not in (None, run_id):
                        raise ValueError("dispatch_identity")
                    locked.workflow_run_id = run_id
                elif message.topic == CANCELLED and job.workflow_run_id:
                    await dispatcher.cancel(payload, run_id=job.workflow_run_id)
                message.status, message.published_at = (
                    OutboxMessageStatus.PUBLISHED,
                    datetime.now(UTC),
                )
                message.last_error = None
                count += 1
            except Exception:
                # Dispatcher failure never exposes remote exception text or model inputs.
                message.attempt_count += 1
                message.last_error = "dispatch_unavailable"
                message.available_at = datetime.now(UTC) + timedelta(seconds=30)
            await session.commit()
    return count


async def recover_style_jobs(
    factory: async_sessionmaker[AsyncSession],
    *,
    dispatcher: ImageDispatcher,
    older_than: timedelta = timedelta(minutes=2),
) -> int:
    async with factory() as session:
        rows = list(
            await session.scalars(
                select(NarrativeStyleJob)
                .where(
                    NarrativeStyleJob.status.in_(ACTIVE),
                    NarrativeStyleJob.workflow_run_id.is_not(None),
                    NarrativeStyleJob.created_at < datetime.now(UTC) - older_than,
                )
                .order_by(NarrativeStyleJob.created_at)
                .limit(20)
            )
        )
    count = 0
    for row in rows:
        assert row.workflow_run_id
        payload = ImageJobPayload(
            schema_version="1", tenant_id=str(row.tenant_id), job_id=str(row.id)
        )
        try:
            if not await dispatcher.closed(payload, run_id=row.workflow_run_id):
                continue
        except Exception:
            continue
        async with factory() as session:
            current = await session.get(NarrativeStyleJob, row.id, with_for_update=True)
            if (
                current
                and current.status in ACTIVE
                and current.workflow_run_id == row.workflow_run_id
            ):
                current.status = "cancelled" if current.cancel_requested else "failed"
                current.error_code = "worker_interrupted"
                current.execution_token = None
                current.finished_at = datetime.now(UTC)
                count += 1
            await session.commit()
    return count
