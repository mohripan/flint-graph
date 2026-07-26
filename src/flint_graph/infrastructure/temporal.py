from typing import Any

from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from flint_graph.application.outbox_contracts import IndexBackfillPayload
from flint_graph.config import Settings
from flint_graph.workflows.backfill import INDEX_BACKFILL_WORKFLOW


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
        await handle.cancel(reason="FlintGraph ingestion job cancelled")


class TemporalIndexBackfillWorkflowStarter:
    def __init__(self, client: Client, *, task_queue: str) -> None:
        self._client = client
        self._task_queue = task_queue

    async def start_index_backfill_workflow(self, *, job_id: object) -> None:
        payload = IndexBackfillPayload(backfill_job_id=str(job_id))
        await self._client.start_workflow(
            INDEX_BACKFILL_WORKFLOW,
            payload,
            id=f"index-backfill-{job_id}",
            task_queue=self._task_queue,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )


async def connect_temporal(settings: Settings) -> Client:
    """Connect to Temporal, propagating trace context when tracing is enabled.

    The interceptor is what carries a trace across the workflow boundary, so a
    request that queues ingestion and the activities that run it land in one
    trace instead of three unrelated ones.
    """
    interceptors: list[Any] = []
    if settings.otel_enabled:
        from temporalio.contrib.opentelemetry import TracingInterceptor

        interceptors.append(TracingInterceptor())
    return await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        interceptors=interceptors,
    )
