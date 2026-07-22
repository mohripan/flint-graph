from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.documents import create_document
from flint_graph.application.services.ingestion_jobs import create_ingestion_job
from flint_graph.application.services.job_cancellation import cancel_ingestion_job
from flint_graph.application.services.outbox_relay import relay_outbox_batch
from flint_graph.application.services.tenants import create_tenant
from flint_graph.domain.enums import OutboxMessageStatus, SourceType
from flint_graph.infrastructure.db.models import OutboxMessage


class RecordingWorkflowStarter:
    def __init__(self) -> None:
        self.started: list[dict[str, Any]] = []
        self.cancelled: list[dict[str, Any]] = []

    async def start_ingestion_workflow(
        self,
        *,
        workflow_id: str,
        payload: dict[str, Any],
        headers: dict[str, Any],
    ) -> None:
        self.started.append(
            {
                "workflow_id": workflow_id,
                "payload": payload,
                "headers": headers,
            }
        )

    async def cancel_ingestion_workflow(
        self,
        *,
        workflow_id: str,
        payload: dict[str, Any],
        headers: dict[str, Any],
    ) -> None:
        self.cancelled.append(
            {
                "workflow_id": workflow_id,
                "payload": payload,
                "headers": headers,
            }
        )


class FailingWorkflowStarter:
    async def start_ingestion_workflow(
        self,
        *,
        workflow_id: str,
        payload: dict[str, Any],
        headers: dict[str, Any],
    ) -> None:
        raise RuntimeError("Temporal is unavailable")

    async def cancel_ingestion_workflow(
        self,
        *,
        workflow_id: str,
        payload: dict[str, Any],
        headers: dict[str, Any],
    ) -> None:
        raise RuntimeError("Temporal is unavailable")


async def _create_pending_outbox_message(db_session: AsyncSession) -> OutboxMessage:
    tenant = await create_tenant(db_session, name="Relay Tenant")
    document = await create_document(
        db_session,
        tenant_id=tenant.id,
        title="Relay Document",
        source_type=SourceType.URL,
        source_uri="https://example.test/relay",
        external_id="relay-document",
    )
    await create_ingestion_job(
        db_session,
        tenant_id=tenant.id,
        document_id=document.id,
        idempotency_key="relay-job",
    )
    message = await db_session.scalar(select(OutboxMessage))
    assert message is not None
    return message


async def _create_pending_cancellation_outbox_message(
    db_session: AsyncSession,
) -> OutboxMessage:
    tenant = await create_tenant(db_session, name="Relay Cancellation Tenant")
    document = await create_document(
        db_session,
        tenant_id=tenant.id,
        title="Relay Cancellation Document",
        source_type=SourceType.URL,
        source_uri="https://example.test/relay-cancel",
        external_id="relay-cancel-document",
    )
    record = await create_ingestion_job(
        db_session,
        tenant_id=tenant.id,
        document_id=document.id,
        idempotency_key="relay-cancel-job",
    )
    await cancel_ingestion_job(db_session, tenant_id=tenant.id, job_id=record.job.id)
    messages = list(
        await db_session.scalars(
            select(OutboxMessage)
        )
    )
    assert len(messages) == 2
    cancellation_message = next(
        message for message in messages if message.topic == "ingestion.job_cancelled"
    )
    return cancellation_message


async def test_relay_publishes_pending_outbox_message(
    db_session: AsyncSession,
) -> None:
    message = await _create_pending_outbox_message(db_session)
    starter = RecordingWorkflowStarter()

    published = await relay_outbox_batch(
        db_session,
        workflow_starter=starter,
        relay_id="test-relay",
    )
    await db_session.refresh(message)

    assert published == 1
    assert message.status == OutboxMessageStatus.PUBLISHED
    assert message.published_at is not None
    assert message.locked_by == "test-relay"
    assert message.last_error is None
    assert starter.started == [
        {
            "workflow_id": f"ingestion-job-{message.aggregate_id}",
            "payload": message.payload,
            "headers": message.headers,
        }
    ]


async def test_relay_skips_already_published_messages(
    db_session: AsyncSession,
) -> None:
    await _create_pending_outbox_message(db_session)
    starter = RecordingWorkflowStarter()

    first = await relay_outbox_batch(
        db_session,
        workflow_starter=starter,
        relay_id="test-relay",
    )
    second = await relay_outbox_batch(
        db_session,
        workflow_starter=starter,
        relay_id="test-relay",
    )

    assert first == 1
    assert second == 0
    assert len(starter.started) == 1


async def test_relay_records_failure_for_retry(
    db_session: AsyncSession,
) -> None:
    message = await _create_pending_outbox_message(db_session)

    with pytest.raises(RuntimeError):
        await relay_outbox_batch(
            db_session,
            workflow_starter=FailingWorkflowStarter(),
            relay_id="test-relay",
        )
    await db_session.refresh(message)

    assert message.status == OutboxMessageStatus.PENDING
    assert message.attempt_count == 1
    assert message.locked_by is None
    assert message.locked_at is None
    assert message.published_at is None
    assert message.last_error == "Temporal is unavailable"


async def test_relay_cancels_workflow_for_cancellation_message(
    db_session: AsyncSession,
) -> None:
    message = await _create_pending_cancellation_outbox_message(db_session)
    starter = RecordingWorkflowStarter()

    published = await relay_outbox_batch(
        db_session,
        workflow_starter=starter,
        relay_id="test-relay",
    )
    await db_session.refresh(message)

    assert published == 2
    assert message.status == OutboxMessageStatus.PUBLISHED
    assert starter.cancelled == [
        {
            "workflow_id": f"ingestion-job-{message.aggregate_id}",
            "payload": message.payload,
            "headers": message.headers,
        }
    ]
