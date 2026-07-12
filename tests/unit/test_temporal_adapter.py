from typing import Any

from atlas_rag.infrastructure.temporal import TemporalIngestionWorkflowStarter


class FakeTemporalClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.handles: list[FakeWorkflowHandle] = []

    async def start_workflow(self, workflow: str, arg: dict[str, Any], **kwargs: Any) -> None:
        self.calls.append({"workflow": workflow, "arg": arg, "kwargs": kwargs})

    def get_workflow_handle(self, workflow_id: str) -> "FakeWorkflowHandle":
        handle = FakeWorkflowHandle(workflow_id)
        self.handles.append(handle)
        return handle


class FakeWorkflowHandle:
    def __init__(self, workflow_id: str) -> None:
        self.workflow_id = workflow_id
        self.cancel_calls: list[dict[str, Any]] = []

    async def cancel(self, **kwargs: Any) -> None:
        self.cancel_calls.append(kwargs)


async def test_temporal_starter_preserves_trace_context_in_workflow_memo() -> None:
    client = FakeTemporalClient()
    starter = TemporalIngestionWorkflowStarter(
        client,  # type: ignore[arg-type]
        task_queue="ingestion",
        workflow_name="IngestDocumentWorkflow",
    )
    headers = {"traceparent": "00-test-trace-test-span-01"}
    payload = {"ingestion_job_id": "job-id"}

    await starter.start_ingestion_workflow(
        workflow_id="ingestion-job-job-id",
        payload=payload,
        headers=headers,
    )

    assert client.calls[0]["kwargs"]["memo"] == {"trace_context": headers}


async def test_temporal_starter_cancels_workflow_by_id() -> None:
    client = FakeTemporalClient()
    starter = TemporalIngestionWorkflowStarter(
        client,  # type: ignore[arg-type]
        task_queue="ingestion",
        workflow_name="IngestDocumentWorkflow",
    )

    await starter.cancel_ingestion_workflow(
        workflow_id="ingestion-job-job-id",
        payload={"ingestion_job_id": "job-id"},
        headers={},
    )

    assert client.handles[0].workflow_id == "ingestion-job-job-id"
    assert client.handles[0].cancel_calls == [{"reason": "AtlasRAG ingestion job cancelled"}]
