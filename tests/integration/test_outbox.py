from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.documents import create_document
from flint_graph.application.services.ingestion_jobs import create_ingestion_job
from flint_graph.application.services.tenants import create_tenant
from flint_graph.domain.enums import SourceType
from flint_graph.infrastructure.db import models


async def test_creating_ingestion_job_appends_outbox_message(
    db_session: AsyncSession,
) -> None:
    assert hasattr(models, "OutboxMessage")

    tenant = await create_tenant(db_session, name="Outbox Tenant")
    document = await create_document(
        db_session,
        tenant_id=tenant.id,
        title="Outbox Document",
        source_type=SourceType.URL,
        source_uri="https://example.test/outbox",
        external_id="outbox-document",
    )

    record = await create_ingestion_job(
        db_session,
        tenant_id=tenant.id,
        document_id=document.id,
        idempotency_key="outbox-job-create",
    )

    outbox_messages = list(await db_session.scalars(select(models.OutboxMessage)))

    assert len(outbox_messages) == 1
    message = outbox_messages[0]
    assert message.topic == "ingestion.job_queued"
    assert message.aggregate_type == "ingestion_job"
    assert message.aggregate_id == record.job.id
    assert message.tenant_id == tenant.id
    assert message.payload["ingestion_job_id"] == str(record.job.id)
    assert message.payload["document_id"] == str(document.id)
    assert message.payload["document_version_id"] == str(record.job.document_version_id)
    assert message.payload["idempotency_key"] == "outbox-job-create"
    assert message.payload["source_type"] == "url"
    assert message.payload["source_uri"] == "https://example.test/outbox"
    assert message.status == models.OutboxMessageStatus.PENDING
    assert message.attempt_count == 0


async def test_idempotent_ingestion_job_replay_does_not_append_second_outbox_message(
    db_session: AsyncSession,
) -> None:
    assert hasattr(models, "OutboxMessage")

    tenant = await create_tenant(db_session, name="Outbox Replay Tenant")
    document = await create_document(
        db_session,
        tenant_id=tenant.id,
        title="Outbox Replay Document",
        source_type=SourceType.URL,
        source_uri="https://example.test/outbox-replay",
        external_id="outbox-replay-document",
    )

    first_record = await create_ingestion_job(
        db_session,
        tenant_id=tenant.id,
        document_id=document.id,
        idempotency_key="outbox-job-replay",
    )
    second_record = await create_ingestion_job(
        db_session,
        tenant_id=tenant.id,
        document_id=document.id,
        idempotency_key="outbox-job-replay",
    )

    outbox_messages = list(await db_session.scalars(select(models.OutboxMessage)))

    assert second_record.job.id == first_record.job.id
    assert len(outbox_messages) == 1
