"""Traces must survive the durable hop.

Before Milestone 14 the outbox captured a traceparent that nothing consumed, so
the trace ended at the API and ingestion produced unrelated spans. These tests
assert continuity through the mechanism the relay actually uses.
"""

from __future__ import annotations

from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.documents import create_document
from flint_graph.application.services.ingestion_jobs import create_ingestion_job
from flint_graph.application.services.outbox_relay import (
    record_outbox_backlog,
    relay_outbox_batch,
)
from flint_graph.application.services.tenants import create_tenant
from flint_graph.domain.enums import SourceType
from flint_graph.infrastructure.db.models import OutboxMessage
from flint_graph.observability.tracing import async_span, span, span_from_carrier

_exporter = InMemorySpanExporter()


@pytest.fixture(scope="module", autouse=True)
def in_memory_tracing() -> InMemorySpanExporter:
    """Install an in-memory tracer provider for this module.

    The global provider can only be set once per process, and no other suite sets
    one (tracing is disabled everywhere else), so this is safe.
    """
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(_exporter))
    trace.set_tracer_provider(provider)
    return _exporter


@pytest.fixture(autouse=True)
def clear_spans() -> None:
    _exporter.clear()


class RecordingWorkflowStarter:
    def __init__(self) -> None:
        self.started: list[dict[str, Any]] = []
        # Captured inside the publish span so the test can assert the trace the
        # workflow would actually join.
        self.trace_ids: list[int] = []

    async def start_ingestion_workflow(
        self,
        *,
        workflow_id: str,
        payload: dict[str, Any],
        headers: dict[str, Any],
    ) -> None:
        self.started.append({"workflow_id": workflow_id, "headers": headers})
        self.trace_ids.append(trace.get_current_span().get_span_context().trace_id)

    async def cancel_ingestion_workflow(
        self,
        *,
        workflow_id: str,
        payload: dict[str, Any],
        headers: dict[str, Any],
    ) -> None:
        raise AssertionError("cancellation is not exercised by this test")


def _spans_by_name() -> dict[str, Any]:
    return {span.name: span for span in _exporter.get_finished_spans()}


async def test_outbox_relay_continues_the_trace_that_queued_the_work(
    db_session: AsyncSession,
) -> None:
    tenant = await create_tenant(db_session, name="Trace Tenant")
    document = await create_document(
        db_session,
        tenant_id=tenant.id,
        title="Traced Document",
        source_type=SourceType.URL,
        source_uri="https://example.test/traced",
        external_id="traced-document",
    )

    # The API request span: the outbox row is written inside it, so its
    # traceparent is what the relay must pick up.
    with span("api.request", **{"http.route": "/v1/documents/{id}/ingestion-jobs"}):
        api_trace_id = trace.get_current_span().get_span_context().trace_id
        await create_ingestion_job(
            db_session,
            tenant_id=tenant.id,
            document_id=document.id,
            idempotency_key="traced-job",
        )

    message = await db_session.scalar(select(OutboxMessage))
    assert message is not None
    assert "traceparent" in message.headers

    starter = RecordingWorkflowStarter()
    published = await relay_outbox_batch(
        db_session,
        workflow_starter=starter,
        relay_id="trace-relay",
    )

    assert published == 1
    publish_span = _spans_by_name()["outbox.publish"]
    assert publish_span.context.trace_id == api_trace_id
    assert starter.trace_ids == [api_trace_id]
    assert publish_span.attributes["flint_graph.outbox.topic"] == message.topic
    assert publish_span.attributes["flint_graph.outbox.message_id"] == str(message.id)


async def test_activity_work_inside_the_publish_span_joins_the_same_trace(
    db_session: AsyncSession,
) -> None:
    """Stands in for the worker: spans opened downstream keep one trace id."""
    with span("api.request"):
        carrier: dict[str, str] = {}
        from flint_graph.application.services.outbox import capture_trace_context

        carrier = capture_trace_context()
        api_trace_id = trace.get_current_span().get_span_context().trace_id

    with span_from_carrier("outbox.publish", carrier):
        async with async_span("activity.run_ingestion_pipeline"):
            pass

    spans = _spans_by_name()
    assert spans["outbox.publish"].context.trace_id == api_trace_id
    assert spans["activity.run_ingestion_pipeline"].context.trace_id == api_trace_id


async def test_a_message_without_trace_context_still_publishes(
    db_session: AsyncSession,
) -> None:
    """Older rows predate trace capture; they must not break the relay."""
    tenant = await create_tenant(db_session, name="Untraced Tenant")
    document = await create_document(
        db_session,
        tenant_id=tenant.id,
        title="Untraced Document",
        source_type=SourceType.URL,
        source_uri="https://example.test/untraced",
        external_id="untraced-document",
    )
    await create_ingestion_job(
        db_session,
        tenant_id=tenant.id,
        document_id=document.id,
        idempotency_key="untraced-job",
    )
    message = await db_session.scalar(select(OutboxMessage))
    assert message is not None
    message.headers = {}
    await db_session.flush()

    published = await relay_outbox_batch(
        db_session,
        workflow_starter=RecordingWorkflowStarter(),
        relay_id="trace-relay",
    )

    assert published == 1
    assert "outbox.publish" in _spans_by_name()


async def test_outbox_backlog_gauges_report_depth_and_lag(
    db_session: AsyncSession,
) -> None:
    tenant = await create_tenant(db_session, name="Backlog Tenant")
    document = await create_document(
        db_session,
        tenant_id=tenant.id,
        title="Backlog Document",
        source_type=SourceType.URL,
        source_uri="https://example.test/backlog",
        external_id="backlog-document",
    )
    await create_ingestion_job(
        db_session,
        tenant_id=tenant.id,
        document_id=document.id,
        idempotency_key="backlog-job",
    )

    pending, oldest_age_seconds = await record_outbox_backlog(db_session)

    assert pending == 1
    assert oldest_age_seconds >= 0.0

    await relay_outbox_batch(
        db_session,
        workflow_starter=RecordingWorkflowStarter(),
        relay_id="trace-relay",
    )
    drained, drained_age = await record_outbox_backlog(db_session)

    assert drained == 0
    assert drained_age == 0.0
