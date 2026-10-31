"""Exact-run, IDs-only image (and voice, ADR 0043) dispatch on its own task queue."""

from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from flint_graph.application.narrative_image_workflow import (
    IMAGE_WORKFLOW,
    ImageJobPayload,
    image_job_workflow_id,
    validate_image_payload,
)

RPC_TIMEOUT = timedelta(seconds=10)


class TemporalImageDispatcher:
    def __init__(
        self,
        client: Client,
        *,
        task_queue: str,
        workflow: str = IMAGE_WORKFLOW,
        workflow_id: Callable[[ImageJobPayload], str] = image_job_workflow_id,
    ) -> None:
        self._client, self._queue = client, task_queue
        self._workflow, self._workflow_id = workflow, workflow_id

    async def start(self, payload: ImageJobPayload) -> UUID:
        data = validate_image_payload(payload)
        workflow_id = self._workflow_id(data)
        try:
            handle = await self._client.start_workflow(
                self._workflow,
                data,
                id=workflow_id,
                task_queue=self._queue,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                execution_timeout=timedelta(hours=2),
                rpc_timeout=RPC_TIMEOUT,
            )
            run_id = handle.first_execution_run_id
        except WorkflowAlreadyStartedError as exc:
            run_id = exc.run_id
            if not run_id:
                # Locate a closed duplicate; its first event below must prove identity.
                description = await self._client.get_workflow_handle(workflow_id).describe(
                    rpc_timeout=RPC_TIMEOUT
                )
                run_id = description.run_id
        try:
            accepted = UUID(str(run_id))
        except (ValueError, TypeError):
            raise ValueError("dispatch_identity") from None
        await self._verified(data, accepted)
        return accepted

    async def _verified(
        self, payload: ImageJobPayload, run_id: UUID
    ) -> WorkflowExecutionStatus | None:
        data = validate_image_payload(payload)
        workflow_id = self._workflow_id(data)
        handle = self._client.get_workflow_handle(workflow_id, run_id=str(run_id))
        description = await handle.describe(rpc_timeout=RPC_TIMEOUT)
        if (
            description.id != workflow_id
            or description.run_id != str(run_id)
            or description.workflow_type != self._workflow
            or description.task_queue != self._queue
        ):
            raise ValueError("dispatch_identity")
        iterator = handle.fetch_history_events(page_size=1, rpc_timeout=RPC_TIMEOUT)
        event = await anext(iterator, None)
        if (
            event is None
            or event.event_id != 1
            or not event.HasField("workflow_execution_started_event_attributes")
        ):
            raise ValueError("dispatch_identity")
        start = event.workflow_execution_started_event_attributes
        if (
            start.workflow_type.name != self._workflow
            or start.task_queue.name != self._queue
            or start.original_execution_run_id != str(run_id)
            or start.continued_execution_run_id
            or start.attempt > 1
            or start.parent_workflow_execution.workflow_id
            or start.cron_schedule
            or start.memo.fields
            or start.header.fields
            or len(start.input.payloads) != 1
        ):
            raise ValueError("dispatch_identity")
        try:
            decoded = await self._client.data_converter.decode(start.input.payloads)
            if validate_image_payload(decoded[0]) != data:
                raise ValueError
        except Exception:
            raise ValueError("dispatch_identity") from None
        return description.status

    async def closed(self, payload: ImageJobPayload, *, run_id: UUID) -> bool:
        status = await self._verified(payload, run_id)
        if status is None:
            raise ValueError("dispatch_identity")
        return status != WorkflowExecutionStatus.RUNNING

    async def cancel(self, payload: ImageJobPayload, *, run_id: UUID) -> None:
        data = validate_image_payload(payload)
        if await self.closed(data, run_id=run_id):
            return
        handle = self._client.get_workflow_handle(self._workflow_id(data), run_id=str(run_id))
        try:
            await handle.cancel(reason="Job cancelled", rpc_timeout=RPC_TIMEOUT)
        except Exception:
            if not await self.closed(data, run_id=run_id):
                raise ValueError("dispatch_unavailable") from None
