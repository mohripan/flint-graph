import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.outbox_contracts import INGESTION_JOB_CANCELLED_TOPIC
from flint_graph.application.services.documents import create_document
from flint_graph.application.services.ingestion_jobs import create_ingestion_job
from flint_graph.application.services.job_cancellation import cancel_ingestion_job
from flint_graph.application.services.job_transitions import transition_ingestion_job
from flint_graph.application.services.tenants import create_tenant
from flint_graph.domain.enums import IngestionJobStatus, SourceType
from flint_graph.domain.errors import ConflictError
from flint_graph.infrastructure.db.models import OutboxMessage


async def test_cancel_queued_ingestion_job_endpoint(client: httpx.AsyncClient) -> None:
    tenant_id = (await client.post("/v1/tenants", json={"name": "Cancel Tenant"})).json()["id"]
    headers = {"X-Tenant-ID": tenant_id}
    document = (
        await client.post(
            "/v1/documents",
            headers=headers,
            json={
                "title": "Cancelable",
                "source_type": "url",
                "source_uri": "https://example.test/cancel",
            },
        )
    ).json()
    job = (
        await client.post(
            f"/v1/documents/{document['id']}/ingestion-jobs",
            headers={**headers, "Idempotency-Key": "cancel-job"},
        )
    ).json()

    response = await client.post(f"/v1/ingestion-jobs/{job['id']}/cancel", headers=headers)
    events_response = await client.get(f"/v1/ingestion-jobs/{job['id']}/events", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    events = events_response.json()
    assert [event["event_type"] for event in events] == ["job.queued", "job.cancelled"]


async def test_cancel_endpoint_preserves_tenant_boundary(client: httpx.AsyncClient) -> None:
    tenant_a = (await client.post("/v1/tenants", json={"name": "Cancel Tenant A"})).json()["id"]
    tenant_b = (await client.post("/v1/tenants", json={"name": "Cancel Tenant B"})).json()["id"]
    document = (
        await client.post(
            "/v1/documents",
            headers={"X-Tenant-ID": tenant_a},
            json={"title": "Private Cancel", "source_type": "upload"},
        )
    ).json()
    job = (
        await client.post(
            f"/v1/documents/{document['id']}/ingestion-jobs",
            headers={"X-Tenant-ID": tenant_a, "Idempotency-Key": "tenant-cancel-job"},
        )
    ).json()

    response = await client.post(
        f"/v1/ingestion-jobs/{job['id']}/cancel",
        headers={"X-Tenant-ID": tenant_b},
    )

    assert response.status_code == 404


async def test_cancel_completed_job_is_rejected(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session, name="Terminal Cancel Tenant")
    document = await create_document(
        db_session,
        tenant_id=tenant.id,
        title="Terminal Cancel",
        source_type=SourceType.URL,
        source_uri="https://example.test/terminal-cancel",
        external_id="terminal-cancel",
    )
    record = await create_ingestion_job(
        db_session,
        tenant_id=tenant.id,
        document_id=document.id,
        idempotency_key="terminal-cancel-job",
    )
    await transition_ingestion_job(
        db_session,
        tenant_id=tenant.id,
        job_id=record.job.id,
        target_status=IngestionJobStatus.RUNNING,
        event_type="job.started",
        details={},
    )
    await transition_ingestion_job(
        db_session,
        tenant_id=tenant.id,
        job_id=record.job.id,
        target_status=IngestionJobStatus.COMPLETED,
        event_type="job.completed",
        details={},
    )

    with pytest.raises(ConflictError):
        await cancel_ingestion_job(db_session, tenant_id=tenant.id, job_id=record.job.id)


async def test_cancel_ingestion_job_appends_cancellation_outbox_message(
    db_session: AsyncSession,
) -> None:
    tenant = await create_tenant(db_session, name="Cancel Outbox Tenant")
    document = await create_document(
        db_session,
        tenant_id=tenant.id,
        title="Cancel Outbox",
        source_type=SourceType.URL,
        source_uri="https://example.test/cancel-outbox",
        external_id="cancel-outbox",
    )
    record = await create_ingestion_job(
        db_session,
        tenant_id=tenant.id,
        document_id=document.id,
        idempotency_key="cancel-outbox-job",
    )

    await cancel_ingestion_job(db_session, tenant_id=tenant.id, job_id=record.job.id)

    messages = list(
        await db_session.scalars(
            select(OutboxMessage)
        )
    )
    messages_by_topic = {message.topic: message for message in messages}
    assert set(messages_by_topic) == {"ingestion.job_queued", INGESTION_JOB_CANCELLED_TOPIC}
    cancellation_message = messages_by_topic[INGESTION_JOB_CANCELLED_TOPIC]
    assert cancellation_message.aggregate_id == record.job.id
    assert cancellation_message.payload["ingestion_job_id"] == str(record.job.id)
