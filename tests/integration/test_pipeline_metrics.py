"""Durable-pipeline instruments must be wired to their call sites.

These are the instruments an operator watches when ingestion stalls, so a
declared-but-never-recorded instrument is a silent gap.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.document_lifecycle import (
    delete_document,
    record_projection_cleanup_backlog,
)
from flint_graph.application.services.documents import create_document
from flint_graph.application.services.index_backfill import (
    complete_backfill_document,
    fail_backfill_document,
)
from flint_graph.application.services.ingestion_jobs import create_ingestion_job
from flint_graph.application.services.job_transitions import transition_ingestion_job
from flint_graph.application.services.retrieval import create_tenant_index_backfill_job
from flint_graph.application.services.retrieval_index_versions import (
    RetrievalIndexVersionSpec,
    activate_retrieval_index_version,
    create_retrieval_index_version,
)
from flint_graph.application.services.tenants import create_tenant
from flint_graph.config import Settings
from flint_graph.domain.enums import (
    IngestionJobStatus,
    RetrievalIndexScope,
    SourceType,
)
from flint_graph.observability import metrics
from flint_graph.observability.instruments import (
    INDEX_BACKFILL_PROGRESS,
    INGESTION_JOB_TRANSITIONS,
    PROJECTION_CLEANUP_BACKLOG,
    InstrumentSpec,
)


@pytest.fixture
def reader() -> Iterator[InMemoryMetricReader]:
    metrics.reset_metrics()
    memory_reader = InMemoryMetricReader()
    metrics.configure_metrics(
        Settings(env="test", otel_enabled=False), extra_readers=[memory_reader]
    )
    yield memory_reader
    metrics.reset_metrics()


def _points(reader: InMemoryMetricReader, spec: InstrumentSpec) -> list[Any]:
    data = reader.get_metrics_data()
    points: list[Any] = []
    for resource_metric in data.resource_metrics if data else []:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                if metric.name == spec.name:
                    points.extend(metric.data.data_points)
    return points


async def _queued_job(session: AsyncSession) -> tuple[UUID, UUID, UUID]:
    tenant = await create_tenant(session, name="Metrics Tenant")
    document = await create_document(
        session,
        tenant_id=tenant.id,
        title="Metrics Document",
        source_type=SourceType.URL,
        source_uri="https://example.test/metrics",
        external_id="metrics-document",
    )
    record = await create_ingestion_job(
        session,
        tenant_id=tenant.id,
        document_id=document.id,
        idempotency_key="metrics-job",
    )
    return tenant.id, document.id, record.job.id


async def test_job_transitions_are_counted_by_terminal_status(
    db_session: AsyncSession, reader: InMemoryMetricReader
) -> None:
    tenant_id, _document_id, job_id = await _queued_job(db_session)

    await transition_ingestion_job(
        db_session,
        tenant_id=tenant_id,
        job_id=job_id,
        target_status=IngestionJobStatus.RUNNING,
        event_type="job.started",
        details={},
    )
    await transition_ingestion_job(
        db_session,
        tenant_id=tenant_id,
        job_id=job_id,
        target_status=IngestionJobStatus.COMPLETED,
        event_type="job.completed",
        details={},
    )

    counts = {
        point.attributes["flint_graph.job.status"]: point.value
        for point in _points(reader, INGESTION_JOB_TRANSITIONS)
    }
    assert counts["running"] == 1
    assert counts["completed"] == 1


async def test_projection_cleanup_backlog_gauge_tracks_pending_work(
    db_session: AsyncSession, reader: InMemoryMetricReader
) -> None:
    tenant_id, document_id, _job_id = await _queued_job(db_session)
    await delete_document(
        db_session,
        tenant_id=tenant_id,
        document_id=document_id,
        reason="metrics test",
    )

    await record_projection_cleanup_backlog(db_session)

    by_status = {
        point.attributes["flint_graph.cleanup.status"]: point.value
        for point in _points(reader, PROJECTION_CLEANUP_BACKLOG)
    }
    # Deleting a document queues cleanups; the gauge is what proves they drain.
    assert set(by_status) == {"pending", "running", "failed"}
    assert by_status["pending"] >= 0
    assert by_status["failed"] == 0


async def test_backfill_document_outcomes_are_counted(
    db_session: AsyncSession, reader: InMemoryMetricReader
) -> None:
    tenant = await create_tenant(db_session, name="Backfill Metrics")
    version = await create_retrieval_index_version(
        db_session,
        scope=RetrievalIndexScope.TENANT,
        tenant_id=tenant.id,
        spec=RetrievalIndexVersionSpec(
            embedding_provider="deterministic",
            embedding_model="backfill-metrics",
            vector_dimension=4,
            embedding_config_hash="sha256:backfill-metrics",
            chunking_schema_version="1",
            chunking_config_hash="sha256:chunking",
            lexical_schema_version="1",
            neo4j_vector_index_name="flint_graph_chunks_backfill_metrics",
            neo4j_vector_property_name="embedding",
            opensearch_index_name="flint_graph_chunks_backfill_metrics",
            opensearch_alias_name="flint_graph_chunks_active",
        ),
    )
    active = await activate_retrieval_index_version(db_session, version_id=version.id)
    job = await create_tenant_index_backfill_job(
        db_session,
        tenant_id=tenant.id,
        retrieval_index_version_id=active.id,
    )
    document = await create_document(
        db_session,
        tenant_id=tenant.id,
        title="Backfilled",
        source_type=SourceType.URL,
        source_uri="https://example.test/backfilled",
        external_id="backfilled-document",
    )
    record = await create_ingestion_job(
        db_session,
        tenant_id=tenant.id,
        document_id=document.id,
        idempotency_key="backfill-metrics-job",
    )
    version_id = record.job.document_version_id
    assert version_id is not None

    await complete_backfill_document(
        db_session, job_id=job.id, document_version_id=version_id
    )
    await fail_backfill_document(
        db_session,
        job_id=job.id,
        document_version_id=version_id,
        error_code="embedding_failed",
        error_message="provider unavailable",
    )

    outcomes = {
        point.attributes["flint_graph.outcome"]: point.value
        for point in _points(reader, INDEX_BACKFILL_PROGRESS)
    }
    assert outcomes == {"completed": 1, "failed": 1}
