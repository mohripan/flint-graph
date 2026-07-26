from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.outbox_contracts import (
    INGESTION_JOB_CANCELLED_TOPIC,
    INGESTION_JOB_QUEUED_TOPIC,
)
from flint_graph.domain.enums import OutboxMessageStatus
from flint_graph.infrastructure.db.models import OutboxMessage
from flint_graph.observability import metrics
from flint_graph.observability.instruments import (
    OUTBOX_OLDEST_PENDING_AGE,
    OUTBOX_PENDING_MESSAGES,
    OUTBOX_RELAY_MESSAGES,
)
from flint_graph.observability.tracing import span_from_carrier


class IngestionWorkflowStarter(Protocol):
    async def start_ingestion_workflow(
        self,
        *,
        workflow_id: str,
        payload: dict[str, Any],
        headers: dict[str, Any],
    ) -> None: ...

    async def cancel_ingestion_workflow(
        self,
        *,
        workflow_id: str,
        payload: dict[str, Any],
        headers: dict[str, Any],
    ) -> None: ...


def ingestion_workflow_id(message: OutboxMessage) -> str:
    return f"ingestion-job-{message.aggregate_id}"


async def _publish_message(
    message: OutboxMessage,
    workflow_starter: IngestionWorkflowStarter,
) -> None:
    if message.topic == INGESTION_JOB_QUEUED_TOPIC:
        await workflow_starter.start_ingestion_workflow(
            workflow_id=ingestion_workflow_id(message),
            payload=message.payload,
            headers=message.headers,
        )
        return
    if message.topic == INGESTION_JOB_CANCELLED_TOPIC:
        await workflow_starter.cancel_ingestion_workflow(
            workflow_id=ingestion_workflow_id(message),
            payload=message.payload,
            headers=message.headers,
        )
        return
    raise ValueError(f"Unsupported outbox topic '{message.topic}'.")


async def relay_outbox_batch(
    session: AsyncSession,
    *,
    workflow_starter: IngestionWorkflowStarter,
    relay_id: str,
    batch_size: int = 10,
    retry_delay_seconds: int = 30,
) -> int:
    messages = list(
        await session.scalars(
            select(OutboxMessage)
            .where(
                OutboxMessage.status == OutboxMessageStatus.PENDING,
                OutboxMessage.topic.in_(
                    [INGESTION_JOB_QUEUED_TOPIC, INGESTION_JOB_CANCELLED_TOPIC]
                ),
                OutboxMessage.available_at <= datetime.now(UTC),
            )
            .order_by(
                OutboxMessage.available_at,
                OutboxMessage.created_at,
                case(
                    (OutboxMessage.topic == INGESTION_JOB_QUEUED_TOPIC, 0),
                    (OutboxMessage.topic == INGESTION_JOB_CANCELLED_TOPIC, 1),
                    else_=2,
                ),
                OutboxMessage.id,
            )
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    )

    published = 0
    for message in messages:
        message.locked_by = relay_id
        message.locked_at = datetime.now(UTC)
        await session.flush()

        # The traceparent captured when the message was written lets the relay
        # continue that trace instead of starting an orphan for the durable hop.
        try:
            with span_from_carrier(
                "outbox.publish",
                message.headers,
                **{
                    "flint_graph.outbox.topic": message.topic,
                    "flint_graph.outbox.message_id": str(message.id),
                    "flint_graph.outbox.attempt": message.attempt_count + 1,
                },
            ):
                await _publish_message(message, workflow_starter)
        except Exception as exc:
            message.status = OutboxMessageStatus.PENDING
            message.attempt_count += 1
            message.locked_by = None
            message.locked_at = None
            message.available_at = datetime.now(UTC) + timedelta(seconds=retry_delay_seconds)
            message.last_error = str(exc)
            await session.flush()
            metrics.add(OUTBOX_RELAY_MESSAGES, **{"flint_graph.outcome": "failed"})
            raise

        message.status = OutboxMessageStatus.PUBLISHED
        message.published_at = datetime.now(UTC)
        message.last_error = None
        await session.flush()
        metrics.add(OUTBOX_RELAY_MESSAGES, **{"flint_graph.outcome": "published"})
        published += 1

    await record_outbox_backlog(session)
    return published


async def record_outbox_backlog(session: AsyncSession) -> tuple[int, float]:
    """Publish outbox depth and lag gauges.

    Lag is the operational signal that matters here: a small pending count with a
    very old head means the relay is stuck on one message, which a count alone
    hides.
    """
    now = datetime.now(UTC)
    pending_count = (
        await session.scalar(
            select(func.count(OutboxMessage.id)).where(
                OutboxMessage.status == OutboxMessageStatus.PENDING
            )
        )
        or 0
    )
    oldest_created_at = await session.scalar(
        select(func.min(OutboxMessage.created_at)).where(
            OutboxMessage.status == OutboxMessageStatus.PENDING
        )
    )
    oldest_age_seconds = 0.0
    if oldest_created_at is not None:
        created_at = oldest_created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        oldest_age_seconds = max(0.0, (now - created_at).total_seconds())

    metrics.set_gauge(OUTBOX_PENDING_MESSAGES, pending_count)
    metrics.set_gauge(OUTBOX_OLDEST_PENDING_AGE, oldest_age_seconds)
    return int(pending_count), oldest_age_seconds
