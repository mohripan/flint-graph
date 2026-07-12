from typing import Any

import pytest
from temporalio.exceptions import CancelledError

from atlas_rag.application.outbox_contracts import IngestionJobQueuedPayload
from atlas_rag.workflows import ingestion
from atlas_rag.workflows.ingestion import (
    MARK_JOB_CANCELLED_ACTIVITY,
    MARK_JOB_COMPLETED_ACTIVITY,
    MARK_JOB_FAILED_ACTIVITY,
    MARK_JOB_RUNNING_ACTIVITY,
    RUN_STUB_INGESTION_ACTIVITY,
    IngestDocumentWorkflow,
)


def _payload() -> IngestionJobQueuedPayload:
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


async def test_ingestion_workflow_runs_stub_path_to_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_execute_activity(activity_name: str, arg: dict[str, Any], **_: Any) -> None:
        calls.append((activity_name, arg))

    monkeypatch.setattr(ingestion.workflow, "execute_activity", fake_execute_activity)

    await IngestDocumentWorkflow().run(_payload())

    assert [name for name, _ in calls] == [
        MARK_JOB_RUNNING_ACTIVITY,
        RUN_STUB_INGESTION_ACTIVITY,
        MARK_JOB_COMPLETED_ACTIVITY,
    ]


async def test_ingestion_workflow_marks_job_failed_when_stub_activity_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_execute_activity(activity_name: str, arg: dict[str, Any], **_: Any) -> None:
        calls.append((activity_name, arg))
        if activity_name == RUN_STUB_INGESTION_ACTIVITY:
            raise RuntimeError("stub ingestion failed")

    monkeypatch.setattr(ingestion.workflow, "execute_activity", fake_execute_activity)

    with pytest.raises(RuntimeError, match="stub ingestion failed"):
        await IngestDocumentWorkflow().run(_payload())

    assert [name for name, _ in calls] == [
        MARK_JOB_RUNNING_ACTIVITY,
        RUN_STUB_INGESTION_ACTIVITY,
        MARK_JOB_FAILED_ACTIVITY,
    ]
    failure_payload = calls[-1][1]
    assert failure_payload["error_code"] == "ingestion_failed"
    assert failure_payload["error_message"] == "stub ingestion failed"


async def test_ingestion_workflow_marks_job_cancelled_when_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_execute_activity(activity_name: str, arg: dict[str, Any], **_: Any) -> None:
        calls.append((activity_name, arg))
        if activity_name == RUN_STUB_INGESTION_ACTIVITY:
            raise CancelledError("cancelled by test")

    monkeypatch.setattr(ingestion.workflow, "execute_activity", fake_execute_activity)

    with pytest.raises(CancelledError):
        await IngestDocumentWorkflow().run(_payload())

    assert [name for name, _ in calls] == [
        MARK_JOB_RUNNING_ACTIVITY,
        RUN_STUB_INGESTION_ACTIVITY,
        MARK_JOB_CANCELLED_ACTIVITY,
    ]
