"""Connected native worker proof against explicit owned services and pinned engine."""

import asyncio
import hashlib
import io
import json
import os
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import select
from temporalio import activity
from temporalio.client import Client
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker
from test_narrative_artifact_store_live import owned_store as owned_store

from flint_graph.api.dependencies import get_narrative_artifact_store
from flint_graph.application.narrative_workflow import (
    ReleasePayload,
    release_workflow_id,
)
from flint_graph.application.services.narrative_release_recovery import recover_narrative_jobs
from flint_graph.application.services.narrative_release_relay import relay_narrative_batch
from flint_graph.config import Settings, get_settings
from flint_graph.infrastructure.db.models import NarrativeReleaseArtifact, NarrativeReleaseJob
from flint_graph.infrastructure.narrative_builder import DockerNarrativeBuilder
from flint_graph.infrastructure.narrative_temporal import TemporalNarrativeDispatcher
from flint_graph.main import app
from flint_graph.worker.activities.narrative_release import NarrativeReleaseActivities
from flint_graph.workflows.narrative_release import NarrativeReleaseWorkflow

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not all(
            os.getenv(key)
            for key in (
                "FLINT_GRAPH_NARRATIVE_PG_URL",
                "FLINT_GRAPH_NARRATIVE_TEMPORAL_FIXTURE",
                "FLINT_GRAPH_NARRATIVE_STORE_FIXTURE",
                "FLINT_GRAPH_NARRATIVE_BUILDER_IMAGE",
                "FLINT_GRAPH_NARRATIVE_BUILDER_TOOLCHAIN",
            )
        ),
        reason="requires explicit owned PostgreSQL, Temporal, MinIO and pinned builder",
    ),
]


@pytest.fixture
async def live_release(narrative_env, owned_store, tmp_path):
    client, factory, backend = narrative_env
    if backend != "postgres":
        pytest.skip("connected worker proof requires real PostgreSQL")
    store, sdk_store, metadata, _key = owned_store
    image, pin = (
        os.environ[name]
        for name in (
            "FLINT_GRAPH_NARRATIVE_BUILDER_IMAGE",
            "FLINT_GRAPH_NARRATIVE_BUILDER_TOOLCHAIN",
        )
    )
    temporal = json.loads(
        await asyncio.to_thread(
            Path(os.environ["FLINT_GRAPH_NARRATIVE_TEMPORAL_FIXTURE"]).read_text
        )
    )
    assert temporal["address"].startswith("127.0.0.1:")
    temporal_client = await Client.connect(temporal["address"], namespace=temporal["namespace"])
    queue = "native-worker-" + uuid4().hex
    scratch = tmp_path / "private-builds"
    await asyncio.to_thread(scratch.mkdir)
    builder = DockerNarrativeBuilder(image=image, toolchain_sha256=pin, work_root=scratch)
    activities = NarrativeReleaseActivities(
        factory=factory,
        builder=builder,
        store=store,
        namespace=temporal["namespace"],
        task_queue=queue,
    )
    dispatcher = TemporalNarrativeDispatcher(temporal_client, task_queue=queue)
    app.dependency_overrides[get_settings] = lambda: Settings(
        env="test",
        narrative_releases_enabled=True,
        narrative_release_builder_image_digest=image,
        narrative_release_toolchain_sha256=pin,
    )
    app.dependency_overrides[get_narrative_artifact_store] = lambda: store
    release_id = None
    try:
        workspace = (await client.post("/v1/workspaces", json={"name": "Native worker"})).json()
        headers = {"X-Tenant-ID": workspace["id"]}
        project = (
            await client.post(
                "/v1/narrative/projects",
                headers=headers,
                json={"name": "Original native fixture", "idempotency_key": str(uuid4())},
            )
        ).json()
        project_path = f"/v1/narrative/projects/{project['id']}"
        revision = (
            await client.get(
                f"{project_path}/revisions/{project['head_revision_id']}", headers=headers
            )
        ).json()
        story = json.loads(revision["story_json"])
        story["title"] = "SYNTHETIC_PRIVATE_STORY_CANARY"
        revised = await client.post(
            f"{project_path}/revisions",
            headers=headers,
            json={
                "base_revision_id": revision["id"],
                "idempotency_key": str(uuid4()),
                "story_json": json.dumps(story),
                "notices": "Original fixture. CC0.\n",
            },
        )
        assert revised.status_code == 201
        release = (
            await client.post(
                f"{project_path}/releases",
                headers=headers,
                json={"revision_id": revised.json()["id"], "idempotency_key": str(uuid4())},
            )
        ).json()
        release_id = UUID(release["id"])
        data = ReleasePayload(
            schema_version="1",
            tenant_id=workspace["id"],
            release_id=release["id"],
            job_id=release["job"]["id"],
        )
        item = f"{project_path}/releases/{release['id']}"
        yield (
            client,
            factory,
            headers,
            item,
            data,
            temporal_client,
            dispatcher,
            queue,
            activities,
            scratch,
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_narrative_artifact_store, None)
        if release_id is not None:
            async with factory() as session:
                keys = list(
                    await session.scalars(
                        select(NarrativeReleaseArtifact.object_key).where(
                            NarrativeReleaseArtifact.release_id == release_id
                        )
                    )
                )
            for key in keys:
                await asyncio.to_thread(sdk_store.delete_object, Bucket=metadata["bucket"], Key=key)


async def test_real_background_dispatch_engine_publication_download_and_private_history(
    live_release,
):
    client, factory, headers, item, data, temporal, dispatcher, queue, activities, scratch = (
        live_release
    )
    # Accept/register without a polling worker: durable queued work survives until startup.
    assert await relay_narrative_batch(factory, dispatcher=dispatcher) == 1
    async with factory() as session:
        job = await session.get(NarrativeReleaseJob, UUID(data["job_id"]))
        run_id = job.workflow_run_id
        assert job.status == "queued" and job.activity_attempt == 0
    async with Worker(
        temporal,
        task_queue=queue,
        workflows=[NarrativeReleaseWorkflow],
        activities=[activities.build, activities.finalize],
        max_concurrent_activities=1,
        max_heartbeat_throttle_interval=timedelta(seconds=1),
    ):
        handle = temporal.get_workflow_handle(release_workflow_id(data), run_id=str(run_id))
        result = await asyncio.wait_for(handle.result(), 90)
        assert result == {"job_id": data["job_id"], "status": "completed"}
        assert await dispatcher.start(data) == run_id
    response = await client.get(item, headers=headers)
    assert response.status_code == 200 and response.json()["job"]["status"] == "completed"
    assert {row["kind"] for row in response.json()["artifacts"]} == {"source", "web", "manifest"}
    downloaded = {}
    for artifact in response.json()["artifacts"]:
        reply = await client.get(f"{item}/artifacts/{artifact['kind']}", headers=headers)
        assert reply.status_code == 200
        assert hashlib.sha256(reply.content).hexdigest() == artifact["sha256"]
        downloaded[artifact["kind"]] = reply.content
    with ZipFile(io.BytesIO(downloaded["source"])) as archive:
        assert "SYNTHETIC_PRIVATE_STORY_CANARY" in archive.read("content/story.json").decode()
    with ZipFile(io.BytesIO(downloaded["web"])) as archive:
        assert "index.wasm" in archive.namelist() and "index.html" in archive.namelist()
    history = (await handle.fetch_history()).to_json()
    assert "SYNTHETIC_PRIVATE_STORY_CANARY" not in history
    assert "object_key" not in history and "/executions/" not in history
    assert list(scratch.iterdir()) == []


class PreclaimFailure:
    def __init__(self):
        self.attempts = []

    @activity.defn(name="build_narrative_release")
    async def build(self, payload: ReleasePayload) -> dict:
        self.attempts.append(activity.info().attempt)
        raise ApplicationError("worker_interrupted", type="worker_interrupted")


async def test_exhaustion_before_first_claim_finalizes_registered_attempt_zero(live_release):
    client, factory, headers, item, data, temporal, dispatcher, queue, activities, scratch = (
        live_release
    )
    assert await relay_narrative_batch(factory, dispatcher=dispatcher) == 1
    probe = PreclaimFailure()
    async with Worker(
        temporal,
        task_queue=queue,
        workflows=[NarrativeReleaseWorkflow],
        activities=[probe.build, activities.finalize],
        max_concurrent_activities=1,
    ):
        handle = temporal.get_workflow_handle(release_workflow_id(data))
        assert await asyncio.wait_for(handle.result(), 25) == {
            "job_id": data["job_id"],
            "status": "failed",
        }
    assert probe.attempts == [1, 2, 3]
    job = (await client.get(item, headers=headers)).json()["job"]
    assert job["status"] == "failed" and job["error_code"] == "worker_interrupted"
    async with factory() as session:
        stored = await session.get(NarrativeReleaseJob, UUID(data["job_id"]))
        assert stored.activity_attempt == 0 and stored.execution_token is None
    assert list(scratch.iterdir()) == []


async def test_periodic_recovery_observes_exact_real_closed_run(live_release):
    client, factory, headers, item, data, temporal, dispatcher, _queue, activities, scratch = (
        live_release
    )
    assert await relay_narrative_batch(factory, dispatcher=dispatcher) == 1
    async with factory() as session:
        job = await session.get(NarrativeReleaseJob, UUID(data["job_id"]))
        run_id = job.workflow_run_id
    live = await recover_narrative_jobs(
        factory, dispatcher=dispatcher, builder=activities.builder, limit=1
    )
    assert live.inspected == 1 and live.recovered == 0 and live.next_id == UUID(data["job_id"])
    end = await recover_narrative_jobs(
        factory, dispatcher=dispatcher, builder=activities.builder, after_id=live.next_id, limit=1
    )
    assert end.inspected == 0 and end.next_id is None
    handle = temporal.get_workflow_handle(release_workflow_id(data), run_id=str(run_id))
    await handle.terminate(reason="Owned native fixture interruption")
    closed = await recover_narrative_jobs(
        factory, dispatcher=dispatcher, builder=activities.builder
    )
    assert closed.inspected == closed.recovered == 1
    job = (await client.get(item, headers=headers)).json()["job"]
    assert job["status"] == "failed" and job["error_code"] == "worker_interrupted"
    assert list(scratch.iterdir()) == []
