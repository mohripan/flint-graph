from typing import Any

from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from atlas_rag.config import Settings


class TemporalIngestionWorkflowStarter:
    def __init__(self, client: Client, *, task_queue: str, workflow_name: str) -> None:
        self._client = client
        self._task_queue = task_queue
        self._workflow_name = workflow_name

    async def start_ingestion_workflow(
        self,
        *,
        workflow_id: str,
        payload: dict[str, Any],
        headers: dict[str, Any],
    ) -> None:
        await self._client.start_workflow(
            self._workflow_name,
            payload,
            id=workflow_id,
            task_queue=self._task_queue,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            memo={"trace_context": headers},
        )

    async def cancel_ingestion_workflow(
        self,
        *,
        workflow_id: str,
        payload: dict[str, Any],
        headers: dict[str, Any],
    ) -> None:
        handle = self._client.get_workflow_handle(workflow_id)
        await handle.cancel(reason="AtlasRAG ingestion job cancelled")


async def connect_temporal(settings: Settings) -> Client:
    return await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
    )
