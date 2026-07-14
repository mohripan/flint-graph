from typing import Any

import pytest
from temporalio.exceptions import CancelledError

from atlas_rag.application.outbox_contracts import IndexBackfillPayload
from atlas_rag.workflows import backfill
from atlas_rag.workflows.backfill import (
    COMPLETE_INDEX_BACKFILL_ACTIVITY,
    FAIL_INDEX_BACKFILL_ACTIVITY,
    INDEX_BACKFILL_WORKFLOW,
    LOAD_INDEX_BACKFILL_BATCH_ACTIVITY,
    MARK_INDEX_BACKFILL_CANCELLED_ACTIVITY,
    MARK_INDEX_BACKFILL_DOCUMENT_COMPLETED_ACTIVITY,
    MARK_INDEX_BACKFILL_DOCUMENT_FAILED_ACTIVITY,
    MARK_INDEX_BACKFILL_RUNNING_ACTIVITY,
    IndexBackfillWorkflow,
)


def _payload() -> IndexBackfillPayload:
    return {
        "backfill_job_id": "032e30a6-14f8-4f3d-8eba-245e7bc4354a",
    }


def _document_payload(version_id: str) -> dict[str, str]:
    return {
        "tenant_id": "6bcb4c0b-f90f-4b9c-9796-f12fcd89707c",
        "document_id": "9f26f9b0-fdb4-4d9e-b544-3299b3d8b64c",
        "document_version_id": version_id,
        "retrieval_index_version_id": "2e326dbf-5a24-4c0f-96fd-0e81c7d1dd8f",
        "source": "backfill",
    }


async def test_backfill_workflow_indexes_batches_and_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Any]] = []
    child_payloads: list[dict[str, str]] = []

    async def fake_execute_activity(activity_name: str, arg: Any, **_: Any) -> Any:
        calls.append((activity_name, arg))
        if activity_name == LOAD_INDEX_BACKFILL_BATCH_ACTIVITY:
            load_count = sum(
                1 for name, _arg in calls if name == LOAD_INDEX_BACKFILL_BATCH_ACTIVITY
            )
            if load_count == 1:
                return {
                    "documents": [
                        _document_payload("749c7dc0-cb96-458e-8096-17c2e098a3fb"),
                        _document_payload("fc6b6655-f2cb-48ce-ab26-62e414ad4f94"),
                    ],
                    "done": False,
                }
            return {"documents": [], "done": True}
        return None

    async def fake_execute_child_workflow(workflow_name: str, arg: Any, **_: Any) -> None:
        calls.append((workflow_name, arg))
        child_payloads.append(arg)

    monkeypatch.setattr(backfill.workflow, "execute_activity", fake_execute_activity)
    monkeypatch.setattr(backfill.workflow, "execute_child_workflow", fake_execute_child_workflow)

    await IndexBackfillWorkflow().run(_payload())

    assert [name for name, _ in calls] == [
        MARK_INDEX_BACKFILL_RUNNING_ACTIVITY,
        LOAD_INDEX_BACKFILL_BATCH_ACTIVITY,
        "IndexDocumentVersionWorkflow",
        MARK_INDEX_BACKFILL_DOCUMENT_COMPLETED_ACTIVITY,
        "IndexDocumentVersionWorkflow",
        MARK_INDEX_BACKFILL_DOCUMENT_COMPLETED_ACTIVITY,
        LOAD_INDEX_BACKFILL_BATCH_ACTIVITY,
        COMPLETE_INDEX_BACKFILL_ACTIVITY,
    ]
    assert [payload["document_version_id"] for payload in child_payloads] == [
        "749c7dc0-cb96-458e-8096-17c2e098a3fb",
        "fc6b6655-f2cb-48ce-ab26-62e414ad4f94",
    ]


async def test_backfill_workflow_records_failed_child_and_marks_job_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Any]] = []

    async def fake_execute_activity(activity_name: str, arg: Any, **_: Any) -> Any:
        calls.append((activity_name, arg))
        if activity_name == LOAD_INDEX_BACKFILL_BATCH_ACTIVITY:
            load_count = sum(
                1 for name, _arg in calls if name == LOAD_INDEX_BACKFILL_BATCH_ACTIVITY
            )
            if load_count == 1:
                return {
                    "documents": [
                        _document_payload("749c7dc0-cb96-458e-8096-17c2e098a3fb")
                    ],
                    "done": False,
                }
            return {"documents": [], "done": True}
        return None

    async def fake_execute_child_workflow(workflow_name: str, arg: Any, **_: Any) -> None:
        calls.append((workflow_name, arg))
        raise RuntimeError("projection failed")

    monkeypatch.setattr(backfill.workflow, "execute_activity", fake_execute_activity)
    monkeypatch.setattr(backfill.workflow, "execute_child_workflow", fake_execute_child_workflow)

    await IndexBackfillWorkflow().run(_payload())

    assert [name for name, _ in calls] == [
        MARK_INDEX_BACKFILL_RUNNING_ACTIVITY,
        LOAD_INDEX_BACKFILL_BATCH_ACTIVITY,
        "IndexDocumentVersionWorkflow",
        MARK_INDEX_BACKFILL_DOCUMENT_FAILED_ACTIVITY,
        LOAD_INDEX_BACKFILL_BATCH_ACTIVITY,
        FAIL_INDEX_BACKFILL_ACTIVITY,
    ]
    failure_payload = calls[3][1]
    assert failure_payload["error_message"] == "projection failed"


async def test_backfill_workflow_marks_cancelled_when_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Any]] = []

    async def fake_execute_activity(activity_name: str, arg: Any, **_: Any) -> Any:
        calls.append((activity_name, arg))
        if activity_name == LOAD_INDEX_BACKFILL_BATCH_ACTIVITY:
            raise CancelledError("cancelled")
        return None

    monkeypatch.setattr(backfill.workflow, "execute_activity", fake_execute_activity)

    with pytest.raises(CancelledError):
        await IndexBackfillWorkflow().run(_payload())

    assert [name for name, _ in calls] == [
        MARK_INDEX_BACKFILL_RUNNING_ACTIVITY,
        LOAD_INDEX_BACKFILL_BATCH_ACTIVITY,
        MARK_INDEX_BACKFILL_CANCELLED_ACTIVITY,
    ]


def test_backfill_workflow_name_is_stable() -> None:
    assert INDEX_BACKFILL_WORKFLOW == "IndexBackfillWorkflow"
