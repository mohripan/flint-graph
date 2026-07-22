from typing import Any

import pytest
from temporalio.exceptions import CancelledError

from flint_graph.application.outbox_contracts import (
    IndexDocumentVersionPayload,
    IngestionJobQueuedPayload,
)
from flint_graph.workflows import indexing, ingestion
from flint_graph.workflows.indexing import (
    INDEX_DOCUMENT_BATCH_ACTIVITY,
    MARK_INDEXING_CANCELLED_ACTIVITY,
    MARK_INDEXING_COMPLETED_ACTIVITY,
    MARK_INDEXING_FAILED_ACTIVITY,
    PLAN_DOCUMENT_INDEXING_ACTIVITY,
    IndexDocumentVersionWorkflow,
)
from flint_graph.workflows.ingestion import (
    ENQUEUE_DOCUMENT_INDEXING_ACTIVITY,
    MARK_JOB_COMPLETED_ACTIVITY,
    MARK_JOB_FAILED_ACTIVITY,
    MARK_JOB_RUNNING_ACTIVITY,
    PREPARE_DOCUMENT_INDEXING_ACTIVITY,
    RUN_INGESTION_PIPELINE_ACTIVITY,
    IngestDocumentWorkflow,
)
from flint_graph.workflows.resolution import ENQUEUE_TENANT_RESOLUTION_ACTIVITY


def _ingestion_payload() -> IngestionJobQueuedPayload:
    return {
        "tenant_id": "6bcb4c0b-f90f-4b9c-9796-f12fcd89707c",
        "document_id": "9f26f9b0-fdb4-4d9e-b544-3299b3d8b64c",
        "document_version_id": "749c7dc0-cb96-458e-8096-17c2e098a3fb",
        "ingestion_job_id": "be45f762-674b-40b5-9200-271c48078d76",
        "idempotency_key": "workflow-test",
        "source_type": "url",
        "source_uri": "https://example.test/workflow",
        "trace_context": {},
    }


def _indexing_payload() -> IndexDocumentVersionPayload:
    return {
        "tenant_id": "6bcb4c0b-f90f-4b9c-9796-f12fcd89707c",
        "document_id": "9f26f9b0-fdb4-4d9e-b544-3299b3d8b64c",
        "document_version_id": "749c7dc0-cb96-458e-8096-17c2e098a3fb",
        "retrieval_index_version_id": "2e326dbf-5a24-4c0f-96fd-0e81c7d1dd8f",
        "source": "ingestion",
    }


async def test_required_ingestion_runs_indexing_before_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    child_payloads: list[IndexDocumentVersionPayload] = []

    async def fake_execute_activity(activity_name: str, arg: Any, **_: Any) -> Any:
        calls.append(activity_name)
        if activity_name == PREPARE_DOCUMENT_INDEXING_ACTIVITY:
            return {
                "mode": "required",
                "should_index": True,
                "payload": _indexing_payload(),
            }
        return None

    async def fake_execute_child_workflow(workflow_name: str, arg: Any, **_: Any) -> None:
        calls.append(workflow_name)
        child_payloads.append(arg)

    monkeypatch.setattr(ingestion.workflow, "execute_activity", fake_execute_activity)
    monkeypatch.setattr(ingestion.workflow, "execute_child_workflow", fake_execute_child_workflow)

    await IngestDocumentWorkflow().run(_ingestion_payload())

    assert calls == [
        MARK_JOB_RUNNING_ACTIVITY,
        RUN_INGESTION_PIPELINE_ACTIVITY,
        PREPARE_DOCUMENT_INDEXING_ACTIVITY,
        "IndexDocumentVersionWorkflow",
        MARK_JOB_COMPLETED_ACTIVITY,
        ENQUEUE_TENANT_RESOLUTION_ACTIVITY,
    ]
    assert child_payloads == [_indexing_payload()]


async def test_optional_ingestion_enqueues_indexing_after_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Any]] = []

    async def fake_execute_activity(activity_name: str, arg: Any, **_: Any) -> Any:
        calls.append((activity_name, arg))
        if activity_name == PREPARE_DOCUMENT_INDEXING_ACTIVITY:
            return {
                "mode": "optional",
                "should_index": True,
                "payload": _indexing_payload(),
            }
        return None

    monkeypatch.setattr(ingestion.workflow, "execute_activity", fake_execute_activity)

    await IngestDocumentWorkflow().run(_ingestion_payload())

    assert [name for name, _ in calls] == [
        MARK_JOB_RUNNING_ACTIVITY,
        RUN_INGESTION_PIPELINE_ACTIVITY,
        PREPARE_DOCUMENT_INDEXING_ACTIVITY,
        MARK_JOB_COMPLETED_ACTIVITY,
        ENQUEUE_DOCUMENT_INDEXING_ACTIVITY,
        ENQUEUE_TENANT_RESOLUTION_ACTIVITY,
    ]
    assert calls[-2][1] == _indexing_payload()


async def test_required_indexing_failure_fails_ingestion_before_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_execute_activity(activity_name: str, arg: Any, **_: Any) -> Any:
        calls.append(activity_name)
        if activity_name == PREPARE_DOCUMENT_INDEXING_ACTIVITY:
            return {
                "mode": "required",
                "should_index": True,
                "payload": _indexing_payload(),
            }
        return None

    async def fake_execute_child_workflow(workflow_name: str, arg: Any, **_: Any) -> None:
        calls.append(workflow_name)
        raise RuntimeError("indexing failed")

    monkeypatch.setattr(ingestion.workflow, "execute_activity", fake_execute_activity)
    monkeypatch.setattr(ingestion.workflow, "execute_child_workflow", fake_execute_child_workflow)

    with pytest.raises(RuntimeError, match="indexing failed"):
        await IngestDocumentWorkflow().run(_ingestion_payload())

    assert calls == [
        MARK_JOB_RUNNING_ACTIVITY,
        RUN_INGESTION_PIPELINE_ACTIVITY,
        PREPARE_DOCUMENT_INDEXING_ACTIVITY,
        "IndexDocumentVersionWorkflow",
        MARK_JOB_FAILED_ACTIVITY,
    ]


async def test_indexing_workflow_batches_and_marks_coverage_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Any]] = []

    async def fake_execute_activity(activity_name: str, arg: Any, **_: Any) -> Any:
        calls.append((activity_name, arg))
        if activity_name == PLAN_DOCUMENT_INDEXING_ACTIVITY:
            return {"batch_count": 2, "chunk_count": 3}
        return {"embedded_count": 1, "vector_count": 1, "lexical_count": 1}

    monkeypatch.setattr(indexing.workflow, "execute_activity", fake_execute_activity)

    await IndexDocumentVersionWorkflow().run(_indexing_payload())

    assert [name for name, _ in calls] == [
        PLAN_DOCUMENT_INDEXING_ACTIVITY,
        INDEX_DOCUMENT_BATCH_ACTIVITY,
        INDEX_DOCUMENT_BATCH_ACTIVITY,
        MARK_INDEXING_COMPLETED_ACTIVITY,
    ]
    assert calls[1][1]["batch_index"] == 0
    assert calls[2][1]["batch_index"] == 1


async def test_indexing_workflow_marks_failed_when_batch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Any]] = []

    async def fake_execute_activity(activity_name: str, arg: Any, **_: Any) -> Any:
        calls.append((activity_name, arg))
        if activity_name == PLAN_DOCUMENT_INDEXING_ACTIVITY:
            return {"batch_count": 1, "chunk_count": 1}
        if activity_name == INDEX_DOCUMENT_BATCH_ACTIVITY:
            raise RuntimeError("embedding provider failed")
        return None

    monkeypatch.setattr(indexing.workflow, "execute_activity", fake_execute_activity)

    with pytest.raises(RuntimeError, match="embedding provider failed"):
        await IndexDocumentVersionWorkflow().run(_indexing_payload())

    assert [name for name, _ in calls] == [
        PLAN_DOCUMENT_INDEXING_ACTIVITY,
        INDEX_DOCUMENT_BATCH_ACTIVITY,
        MARK_INDEXING_FAILED_ACTIVITY,
    ]
    assert calls[-1][1]["error_message"] == "embedding provider failed"


async def test_indexing_workflow_marks_cancelled_when_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Any]] = []

    async def fake_execute_activity(activity_name: str, arg: Any, **_: Any) -> Any:
        calls.append((activity_name, arg))
        if activity_name == PLAN_DOCUMENT_INDEXING_ACTIVITY:
            raise CancelledError("cancelled by test")
        return None

    monkeypatch.setattr(indexing.workflow, "execute_activity", fake_execute_activity)

    with pytest.raises(CancelledError):
        await IndexDocumentVersionWorkflow().run(_indexing_payload())

    assert [name for name, _ in calls] == [
        PLAN_DOCUMENT_INDEXING_ACTIVITY,
        MARK_INDEXING_CANCELLED_ACTIVITY,
    ]
