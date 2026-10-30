"""Opt-in narrative dispatch; never consumes ingestion or other outbox topics."""

from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flint_graph.application.narrative_workflow import (
    CANCELLED_TOPIC,
    QUEUED_TOPIC,
    ReleasePayload,
    validate_release_payload,
)
from flint_graph.application.services.narrative_release_execution import register_release_workflow
from flint_graph.domain.enums import OutboxMessageStatus
from flint_graph.infrastructure.db.models import NarrativeReleaseJob, OutboxMessage


class NarrativeDispatcher(Protocol):
    async def start(self, payload: ReleasePayload) -> UUID: ...

    async def cancel(self, payload: ReleasePayload, *, run_id: UUID) -> None: ...


async def relay_narrative_message(
    session: AsyncSession,
    *,
    dispatcher: NarrativeDispatcher,
    retry_delay_seconds: int = 30,
) -> bool | None:
    """Caller commits acknowledgements and accepted-run ownership together.

    A lost commit replays the exact same Temporal run. Per-message savepoints
    prevent a bad record or unavailable service from starving independent work.
    Raw exceptions and trace headers never enter history or persisted errors.
    """
    if not 1 <= retry_delay_seconds <= 3600:
        raise ValueError("Invalid narrative relay limits")
    messages = list(
        await session.scalars(
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
    )
    if not messages:
        return None
    message = messages[0]
    message_id = message.id
    try:
        async with session.begin_nested():
            payload = validate_release_payload(message.payload)
            if (
                message.aggregate_type != "narrative_release_job"
                or message.aggregate_id != UUID(payload["job_id"])
                or message.tenant_id != UUID(payload["tenant_id"])
            ):
                raise ValueError("Invalid narrative dispatch identity")
            scope = dict(
                tenant_id=message.tenant_id,
                release_id=UUID(payload["release_id"]),
                job_id=message.aggregate_id,
            )
            job = await session.scalar(
                select(NarrativeReleaseJob)
                .where(
                    NarrativeReleaseJob.id == scope["job_id"],
                    NarrativeReleaseJob.tenant_id == scope["tenant_id"],
                    NarrativeReleaseJob.release_id == scope["release_id"],
                )
                .execution_options(populate_existing=True)
            )
            if job is None:
                raise ValueError("Invalid narrative dispatch identity")
            if job.status in ("queued", "running"):
                if message.topic == QUEUED_TOPIC:
                    if job.workflow_run_id is None and job.status != "queued":
                        raise ValueError("Unowned narrative execution")
                    run_id = await dispatcher.start(payload)
                    await register_release_workflow(session, **scope, workflow_run_id=run_id)
                else:
                    if job.workflow_run_id is None:
                        raise ValueError("Narrative dispatch registration pending")
                    await dispatcher.cancel(payload, run_id=job.workflow_run_id)
            # Terminal database jobs need no engine/workflow launch or cancellation.
            message.status = OutboxMessageStatus.PUBLISHED
            message.published_at = datetime.now(UTC)
            message.last_error = None
            message.locked_by = message.locked_at = None
            await session.flush()
        return True
    except Exception:
        # A rolled-back savepoint expires touched ORM state; re-read by the
        # immutable id, captured without exposing driver/provider text.
        failed_message = await session.get(OutboxMessage, message_id, populate_existing=True)
        if failed_message is None:
            return False
        failed_message.attempt_count += 1
        failed_message.available_at = datetime.now(UTC) + timedelta(seconds=retry_delay_seconds)
        failed_message.last_error = "dispatch_unavailable"
        failed_message.locked_by = failed_message.locked_at = None
        await session.flush()
    return False


async def relay_narrative_batch(
    factory: async_sessionmaker[AsyncSession],
    *,
    dispatcher: NarrativeDispatcher,
    batch_size: int = 10,
    retry_delay_seconds: int = 30,
) -> int:
    """Publish each registration before issuing the next message's RPC."""
    if not 1 <= batch_size <= 100:
        raise ValueError("Invalid narrative relay limits")
    published = 0
    for _ in range(batch_size):
        async with factory() as session:
            result = await relay_narrative_message(
                session, dispatcher=dispatcher, retry_delay_seconds=retry_delay_seconds
            )
            await session.commit()
        if result is None:
            break
        published += int(result)
    return published
