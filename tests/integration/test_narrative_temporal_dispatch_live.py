"""Explicit owned-server qualification of the real SDK dispatch adapter."""

import asyncio
import json
import os
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from temporalio import workflow
from temporalio.client import Client, WorkflowExecutionStatus, WorkflowFailureError
from temporalio.exceptions import CancelledError
from temporalio.worker import Worker

from flint_graph.application.narrative_workflow import (
    NARRATIVE_RELEASE_WORKFLOW,
    ReleasePayload,
    release_workflow_id,
)
from flint_graph.infrastructure.narrative_temporal import TemporalNarrativeDispatcher

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("FLINT_GRAPH_NARRATIVE_TEMPORAL_FIXTURE"),
        reason="requires an explicit owned Temporal fixture metadata file",
    ),
]


@workflow.defn(name=NARRATIVE_RELEASE_WORKFLOW)
class DispatchProbe:
    @workflow.run
    async def run(self, payload: ReleasePayload) -> dict[str, str]:
        return {"job_id": payload["job_id"], "status": "completed"}


@workflow.defn(name=NARRATIVE_RELEASE_WORKFLOW)
class BlockingDispatchProbe:
    @workflow.run
    async def run(self, payload: ReleasePayload) -> dict[str, str]:
        await workflow.wait_condition(lambda: False)
        return {"job_id": payload["job_id"], "status": "completed"}


@pytest.fixture
async def temporal_dispatch():
    owned = json.loads(
        await asyncio.to_thread(
            Path(os.environ["FLINT_GRAPH_NARRATIVE_TEMPORAL_FIXTURE"]).read_text
        )
    )
    assert owned["container_name"].startswith("flint-narrative-temporal-")
    assert owned["address"].startswith("127.0.0.1:")
    client = await Client.connect(owned["address"], namespace=owned["namespace"])
    queue = "dispatch-probe-" + uuid4().hex
    yield client, TemporalNarrativeDispatcher(client, task_queue=queue), queue


def payload():
    return ReleasePayload(
        schema_version="1", tenant_id=str(uuid4()), release_id=str(uuid4()), job_id=str(uuid4())
    )


async def test_closed_duplicate_replays_verified_original_run_with_no_private_memo(
    temporal_dispatch,
):
    from opentelemetry import baggage, context

    client, dispatcher, queue = temporal_dispatch
    data = payload()
    attached = context.attach(baggage.set_baggage("private", "SYNTHETIC_PRIVATE_CANARY"))
    try:
        async with Worker(client, task_queue=queue, workflows=[DispatchProbe]):
            first = await dispatcher.start(data)
            handle = client.get_workflow_handle(release_workflow_id(data), run_id=str(first))
            result = await asyncio.wait_for(handle.result(), 20)
            assert result == {"job_id": data["job_id"], "status": "completed"}
            assert await dispatcher.start(data) == first
            assert await dispatcher.closed(data, run_id=first)
            await dispatcher.cancel(data, run_id=first)  # terminal cancel replay is harmless
            history = await handle.fetch_history()
            serialized = history.to_json()
            assert "SYNTHETIC_PRIVATE_CANARY" not in serialized
            assert "baggage" not in serialized
            start = history.events[0].workflow_execution_started_event_attributes
            assert not start.memo.fields and not start.header.fields
    finally:
        context.detach(attached)


async def test_running_duplicate_and_exact_run_cancellation(temporal_dispatch):
    client, dispatcher, queue = temporal_dispatch
    data = payload()
    first = await dispatcher.start(data)  # no worker polls yet
    assert await dispatcher.start(data) == first
    assert not await dispatcher.closed(data, run_id=first)
    await dispatcher.cancel(data, run_id=first)
    async with Worker(client, task_queue=queue, workflows=[BlockingDispatchProbe]):
        handle = client.get_workflow_handle(release_workflow_id(data), run_id=str(first))
        with pytest.raises(WorkflowFailureError) as failure:
            await asyncio.wait_for(handle.result(), 20)
        assert isinstance(failure.value.cause, CancelledError)
        assert (await handle.describe()).status == WorkflowExecutionStatus.CANCELED
    assert await dispatcher.closed(data, run_id=first)


async def test_existing_wrong_input_is_rejected_without_starting_a_new_run(temporal_dispatch):
    client, dispatcher, queue = temporal_dispatch
    data = payload()
    wrong = {**data, "release_id": str(uuid4())}
    async with Worker(client, task_queue=queue, workflows=[DispatchProbe]):
        original = await client.start_workflow(
            NARRATIVE_RELEASE_WORKFLOW,
            wrong,
            id=release_workflow_id(data),
            task_queue=queue,
            rpc_timeout=timedelta(seconds=10),
        )
        await asyncio.wait_for(original.result(), 20)
        with pytest.raises(ValueError, match="dispatch_identity"):
            await dispatcher.start(data)
        assert (await original.describe()).run_id == original.first_execution_run_id
