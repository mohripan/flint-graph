"""SDK activity context and database effects; default tests launch no engine."""

import asyncio
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from flint_graph.application.narrative_workflow import (
    BUILD_ACTIVITY_ID,
    BUILD_NARRATIVE_RELEASE_ACTIVITY,
    NARRATIVE_RELEASE_WORKFLOW,
    ReleasePayload,
    release_workflow_id,
)
from flint_graph.application.services.narrative_release_execution import (
    claim_release_execution,
    register_release_workflow,
)
from flint_graph.config import Settings, get_settings
from flint_graph.infrastructure.db.models import NarrativeReleaseJob
from flint_graph.infrastructure.narrative_artifact_store import S3NarrativeArtifactStore
from flint_graph.infrastructure.narrative_builder import DockerNarrativeBuilder
from flint_graph.main import app
from flint_graph.worker.activities.narrative_release import NarrativeReleaseActivities


@pytest.fixture
async def activity_case(narrative_env, tmp_path):
    client, factory, _backend = narrative_env
    app.dependency_overrides[get_settings] = lambda: Settings(
        env="test",
        narrative_releases_enabled=True,
        narrative_release_builder_image_digest="sha256:" + "a" * 64,
        narrative_release_toolchain_sha256="b" * 64,
    )
    try:
        workspace = (await client.post("/v1/workspaces", json={"name": "Activity"})).json()
        headers = {"X-Tenant-ID": workspace["id"]}
        project = (
            await client.post(
                "/v1/narrative/projects",
                headers=headers,
                json={"name": "PRIVATE CANARY", "idempotency_key": str(uuid4())},
            )
        ).json()
        path = f"/v1/narrative/projects/{project['id']}/releases"
        release = (
            await client.post(
                path,
                headers=headers,
                json={"revision_id": project["head_revision_id"], "idempotency_key": str(uuid4())},
            )
        ).json()
        payload = ReleasePayload(
            schema_version="1",
            tenant_id=workspace["id"],
            release_id=release["id"],
            job_id=release["job"]["id"],
        )
        # Deliberately different pinned identity: fail before reading/launching Docker.
        scratch = tmp_path / "build-scratch"
        await asyncio.to_thread(scratch.mkdir)
        builder = DockerNarrativeBuilder(
            image="sha256:" + "c" * 64,
            toolchain_sha256="d" * 64,
            work_root=scratch,
            docker_command=("MUST_NOT_LAUNCH",),
        )
        activities = NarrativeReleaseActivities(
            factory=factory,
            builder=builder,
            store=S3NarrativeArtifactStore(object(), bucket="unused-fixture"),
            namespace="activity-fixture",
            task_queue="activity-fixture",
        )
        env = ActivityEnvironment()
        run_id = uuid4()
        env.info = replace(
            env.info,
            activity_id=BUILD_ACTIVITY_ID,
            activity_type=BUILD_NARRATIVE_RELEASE_ACTIVITY,
            namespace="activity-fixture",
            task_queue="activity-fixture",
            workflow_id=release_workflow_id(payload),
            workflow_type=NARRATIVE_RELEASE_WORKFLOW,
            workflow_run_id=str(run_id),
            attempt=1,
        )
        yield factory, payload, activities, env, run_id, scratch
    finally:
        app.dependency_overrides.pop(get_settings, None)


async def register(factory, payload, run_id):
    async with factory() as session:
        await register_release_workflow(
            session,
            tenant_id=UUID(payload["tenant_id"]),
            release_id=UUID(payload["release_id"]),
            job_id=UUID(payload["job_id"]),
            workflow_run_id=run_id,
        )
        await session.commit()


@pytest.mark.anyio
async def test_wrong_sdk_activity_identity_cannot_claim_or_launch(activity_case):
    factory, payload, activities, env, run_id, scratch = activity_case
    await register(factory, payload, run_id)
    env.info = replace(env.info, activity_id="another-chain")
    with pytest.raises(ApplicationError, match="activity_identity") as error:
        await env.run(activities.build, payload)
    assert error.value.non_retryable
    async with factory() as session:
        job = await session.get(NarrativeReleaseJob, UUID(payload["job_id"]))
        assert job.status == "queued" and job.execution_token is None and job.activity_attempt == 0
    assert list(scratch.iterdir()) == []


@pytest.mark.anyio
async def test_registration_race_retries_without_claiming_or_false_success(activity_case):
    factory, payload, activities, env, _run_id, scratch = activity_case
    with pytest.raises(ApplicationError, match="execution_registration_pending") as error:
        await env.run(activities.build, payload)
    assert not error.value.non_retryable and "PRIVATE" not in str(error.value)
    async with factory() as session:
        job = await session.get(NarrativeReleaseJob, UUID(payload["job_id"]))
        assert (
            job.status == "queued" and job.workflow_run_id is None and job.execution_token is None
        )
    assert list(scratch.iterdir()) == []


@pytest.mark.anyio
async def test_owned_unavailable_toolchain_fails_safely_without_launch_or_storage(activity_case):
    factory, payload, activities, env, run_id, scratch = activity_case
    await register(factory, payload, run_id)
    heartbeats = []
    env.on_heartbeat = lambda *details: heartbeats.extend(details)
    assert await env.run(activities.build, payload) == {
        "job_id": payload["job_id"],
        "status": "failed",
    }
    async with factory() as session:
        job = await session.get(NarrativeReleaseJob, UUID(payload["job_id"]))
        assert job.status == "failed" and job.error_code == "runtime_unavailable"
        assert (
            job.execution_token is None
            and job.workflow_run_id == run_id
            and job.activity_attempt == 1
        )
    assert list(scratch.iterdir()) == []
    assert all(detail == {"job_id": payload["job_id"]} for detail in heartbeats)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "reason", ["timed_out", "not_found", "worker_shutdown", "cancel_requested"]
)
async def test_lease_loss_preserves_retry_and_explicit_cancel_finalizes(activity_case, reason):
    factory, payload, original, env, run_id, scratch = activity_case
    entered = asyncio.Event()

    class HeldBuilder(DockerNarrativeBuilder):
        async def build(self, package, *, execution_id, check):
            await check()
            entered.set()
            await asyncio.Event().wait()  # controlled external build latency, no engine claim

    builder = HeldBuilder(
        image="sha256:" + "a" * 64,
        toolchain_sha256="b" * 64,
        work_root=scratch,
        docker_command=("MUST_NOT_LAUNCH",),
    )
    activities = NarrativeReleaseActivities(
        factory=factory,
        builder=builder,
        store=original.store,
        namespace="activity-fixture",
        task_queue="activity-fixture",
    )
    await register(factory, payload, run_id)
    task = asyncio.create_task(env.run(activities.build, payload))
    await asyncio.wait_for(entered.wait(), 5)
    env.cancel(activity.ActivityCancellationDetails(**{reason: True}))
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    async with factory() as session:
        job = await session.get(NarrativeReleaseJob, UUID(payload["job_id"]))
        if reason == "cancel_requested":
            assert (
                job.status == "cancelled" and job.cancel_requested and job.execution_token is None
            )
        else:
            assert job.status == "running" and not job.cancel_requested
            replacement = await claim_release_execution(
                session,
                tenant_id=UUID(payload["tenant_id"]),
                release_id=UUID(payload["release_id"]),
                job_id=UUID(payload["job_id"]),
                token=uuid4(),
                workflow_run_id=run_id,
                activity_attempt=2,
            )
            assert replacement.acquired and not replacement.state.cancel_requested
            await session.commit()
    assert list(scratch.iterdir()) == []
