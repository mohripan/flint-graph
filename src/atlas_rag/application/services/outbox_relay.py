from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.outbox_contracts import (
    INGESTION_JOB_CANCELLED_TOPIC,
    INGESTION_JOB_QUEUED_TOPIC,
)
from atlas_rag.domain.enums import OutboxMessageStatus
from atlas_rag.infrastructure.db.models import OutboxMessage


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
            .order_by(OutboxMessage.available_at, OutboxMessage.created_at, OutboxMessage.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    )

    published = 0
    for message in messages:
        message.locked_by = relay_id
        message.locked_at = datetime.now(UTC)
        await session.flush()

        try:
            await _publish_message(message, workflow_starter)
        except Exception as exc:
            message.status = OutboxMessageStatus.PENDING
            message.attempt_count += 1
            message.locked_by = None
            message.locked_at = None
            message.available_at = datetime.now(UTC) + timedelta(seconds=retry_delay_seconds)
            message.last_error = str(exc)
            await session.flush()
            raise

        message.status = OutboxMessageStatus.PUBLISHED
        message.published_at = datetime.now(UTC)
        message.last_error = None
        await session.flush()
        published += 1

    return published
