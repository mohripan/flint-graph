"""Real Temporal policy tests at workflow/activity boundaries; no engine claim."""

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from temporalio import activity
from temporalio.client import Client, WorkflowFailureError
from temporalio.exceptions import ApplicationError, CancelledError
from temporalio.worker import Worker

from flint_graph.application.narrative_workflow import ReleasePayload, release_workflow_id
from flint_graph.workflows.narrative_release import NarrativeReleaseWorkflow

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("FLINT_GRAPH_NARRATIVE_TEMPORAL_FIXTURE"),
        reason="requires an explicit owned Temporal fixture metadata file",
    ),
]


class ProbeActivities:
    def __init__(self, mode):
        self.mode, self.calls = mode, []
        self.started, self.finalizing, self.finish = (asyncio.Event() for _ in range(3))

    @activity.defn(name="build_narrative_release")
    async def build(self, payload: dict) -> dict:
        info = activity.info()
        self.calls.append((info.activity_id, info.attempt, info.workflow_run_id))
        self.started.set()
        if self.mode == "fail":
            raise ApplicationError("worker_interrupted", type="worker_interrupted")
        if self.mode == "wrong_job":
            return {"job_id": str(uuid4()), "status": "completed"}
        if self.mode == "extra":
            return {"job_id": payload["job_id"], "status": "completed", "unexpected": True}
        if self.mode == "cancel":
            while True:
                activity.heartbeat({"job_id": payload["job_id"]})
                await asyncio.sleep(0.05)
        return {"job_id": payload["job_id"], "status": "completed"}

    @activity.defn(name="finalize_narrative_release")
    async def finalize(self, payload: dict) -> dict:
        info = activity.info()
        self.calls.append((info.activity_id, info.attempt, info.workflow_run_id))
        assert set(payload) == {"schema_version", "tenant_id", "release_id", "job_id", "cancelled"}
        self.finalizing.set()
        if self.mode == "cancel":
            await self.finish.wait()
        return {
            "job_id": payload["job_id"],
            "status": "cancelled" if payload["cancelled"] else "failed",
        }


@pytest.fixture
async def policy_case():
    owned = json.loads(
        await asyncio.to_thread(
            Path(os.environ["FLINT_GRAPH_NARRATIVE_TEMPORAL_FIXTURE"]).read_text
        )
    )
    assert owned["address"].startswith("127.0.0.1:")
    client = await Client.connect(owned["address"], namespace=owned["namespace"])
    data = ReleasePayload(
        schema_version="1", tenant_id=str(uuid4()), release_id=str(uuid4()), job_id=str(uuid4())
    )
    return client, "policy-" + uuid4().hex, data


@pytest.mark.parametrize(
    "mode,expected",
    [("success", "completed"), ("fail", "failed"), ("wrong_job", "failed"), ("extra", "failed")],
)
async def test_single_build_chain_and_bounded_retry_exhaustion(policy_case, mode, expected):
    client, queue, data = policy_case
    probe = ProbeActivities(mode)
    async with Worker(
        client,
        task_queue=queue,
        workflows=[NarrativeReleaseWorkflow],
        activities=[probe.build, probe.finalize],
        max_concurrent_activities=1,
    ):
        handle = await client.start_workflow(
            NarrativeReleaseWorkflow.run, data, id=release_workflow_id(data), task_queue=queue
        )
        assert await asyncio.wait_for(handle.result(), 25) == {
            "job_id": data["job_id"],
            "status": expected,
        }
    if mode == "success":
        assert [call[:2] for call in probe.calls] == [("build-release", 1)]
    elif mode == "fail":
        assert [call[:2] for call in probe.calls] == [
            ("build-release", 1),
            ("build-release", 2),
            ("build-release", 3),
            ("finalize-release", 1),
        ]
    else:
        assert [call[:2] for call in probe.calls] == [("build-release", 1), ("finalize-release", 1)]
    assert {call[2] for call in probe.calls} == {handle.first_execution_run_id}


async def test_repeated_workflow_cancel_waits_for_shielded_finalization(policy_case):
    client, queue, data = policy_case
    probe = ProbeActivities("cancel")
    async with Worker(
        client,
        task_queue=queue,
        workflows=[NarrativeReleaseWorkflow],
        activities=[probe.build, probe.finalize],
        max_concurrent_activities=1,
        max_heartbeat_throttle_interval=__import__("datetime").timedelta(seconds=0.1),
    ):
        handle = await client.start_workflow(
            NarrativeReleaseWorkflow.run, data, id=release_workflow_id(data), task_queue=queue
        )
        await asyncio.wait_for(probe.started.wait(), 10)
        await handle.cancel()
        await asyncio.wait_for(probe.finalizing.wait(), 10)
        await handle.cancel()
        probe.finish.set()
        with pytest.raises(WorkflowFailureError) as failure:
            await asyncio.wait_for(handle.result(), 15)
        assert isinstance(failure.value.cause, CancelledError)
    assert [call[:2] for call in probe.calls] == [("build-release", 1), ("finalize-release", 1)]
