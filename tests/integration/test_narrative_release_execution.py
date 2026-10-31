"""Worker fencing through persisted transitions and public inspection APIs."""

import asyncio
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from flint_graph.application.services.narrative_release_execution import (
    ReleaseInputError,
    claim_release_execution,
    finalize_release_workflow,
    finish_release_failure,
    load_release_input,
    register_release_workflow,
    workflow_cleanup_plan,
)
from flint_graph.application.services.narrative_release_recovery import (
    recover_narrative_jobs,
    run_narrative_maintenance,
)
from flint_graph.application.services.narrative_releases import BuildIdentity
from flint_graph.config import Settings, get_settings
from flint_graph.domain.errors import NotFoundError
from flint_graph.infrastructure.db.models import NarrativeRelease, NarrativeReleaseJob
from flint_graph.main import app


class ClosedRunBoundary:
    def __init__(self, closed):
        self.is_closed = closed

    async def closed(self, payload, *, run_id):
        return self.is_closed


class CleanupBoundary:
    def __init__(self):
        self.tokens = []
        self.entered = asyncio.Event()
        self.proceed = asyncio.Event()
        self.proceed.set()

    async def cleanup_execution(self, token):
        self.tokens.append(token)
        self.entered.set()
        await self.proceed.wait()

    async def sweep_expired(self):
        self.entered.set()
        await self.proceed.wait()
        return 0


@pytest.mark.anyio
async def test_blocked_sweep_cannot_delay_database_closed_run_recovery(execution_case):
    client, factory, _, headers, item, scope, _ = execution_case
    async with factory() as session:
        await register_release_workflow(session, **scope, workflow_run_id=uuid4())
        await session.commit()
    cleaner = CleanupBoundary()
    cleaner.proceed.clear()
    task = asyncio.create_task(
        run_narrative_maintenance(
            factory, dispatcher=ClosedRunBoundary(True), builder=cleaner, interval_seconds=5
        )
    )
    try:
        await asyncio.wait_for(cleaner.entered.wait(), 5)
        for _ in range(100):
            if (await client.get(item, headers=headers)).json()["job"]["status"] == "failed":
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("A held sweep prevented independent database recovery")
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.anyio
async def test_blocked_run_inspection_respects_pass_budget_and_advances_cursor(execution_case):
    _, factory, _, _, _, scope, _ = execution_case
    async with factory() as session:
        await register_release_workflow(session, **scope, workflow_run_id=uuid4())
        await session.commit()

    class BlockedInspector:
        async def closed(self, payload, *, run_id):
            await asyncio.Event().wait()

    result = await asyncio.wait_for(
        recover_narrative_jobs(
            factory,
            dispatcher=BlockedInspector(),
            builder=CleanupBoundary(),
            limit=1,
            pass_budget_seconds=0.05,
        ),
        2,
    )
    assert result.inspected == 1 and result.recovered == 0 and result.next_id == scope["job_id"]


@pytest.mark.anyio
async def test_periodic_recovery_skips_live_run_and_finalizes_closed_registered_zero(
    execution_case,
):
    client, factory, _, headers, item, scope, _ = execution_case
    run_id, inspector, cleanup = uuid4(), ClosedRunBoundary(False), CleanupBoundary()
    async with factory() as session:
        await register_release_workflow(session, **scope, workflow_run_id=run_id)
        await session.commit()
    first = await recover_narrative_jobs(factory, dispatcher=inspector, builder=cleanup)
    assert first.inspected == 1 and first.recovered == 0
    assert (await client.get(item, headers=headers)).json()["job"]["status"] == "queued"
    inspector.is_closed = True
    second = await recover_narrative_jobs(factory, dispatcher=inspector, builder=cleanup)
    assert second.inspected == 1 and second.recovered == 1
    assert (await client.get(item, headers=headers)).json()["job"]["status"] == "failed"
    assert not cleanup.tokens
    replay = await recover_narrative_jobs(factory, dispatcher=inspector, builder=cleanup)
    assert replay.inspected == replay.recovered == 0


@pytest.mark.anyio
async def test_periodic_recovery_cleanup_releases_locks_and_cannot_finalize_replacement(
    execution_case,
):
    client, factory, _, headers, item, scope, _ = execution_case
    run_id, old, new = uuid4(), uuid4(), uuid4()
    cleanup = CleanupBoundary()
    cleanup.proceed.clear()
    async with factory() as session:
        await register_release_workflow(session, **scope, workflow_run_id=run_id)
        await claim_release_execution(
            session, **scope, token=old, workflow_run_id=run_id, activity_attempt=1
        )
        await session.commit()
    task = asyncio.create_task(
        recover_narrative_jobs(factory, dispatcher=ClosedRunBoundary(True), builder=cleanup)
    )
    try:
        await asyncio.wait_for(cleanup.entered.wait(), 5)
        async with factory() as session:
            replacement = await asyncio.wait_for(
                claim_release_execution(
                    session, **scope, token=new, workflow_run_id=run_id, activity_attempt=2
                ),
                5,
            )
            assert replacement.acquired
            await session.commit()
    finally:
        cleanup.proceed.set()
        result = await asyncio.wait_for(task, 5)
    assert result.recovered == 0 and cleanup.tokens == [old]
    assert (await client.get(item, headers=headers)).json()["job"]["status"] == "running"


@pytest.fixture
async def execution_case(narrative_env):
    client, factory, backend = narrative_env
    build = BuildIdentity("sha256:" + "a" * 64, "b" * 64)
    app.dependency_overrides[get_settings] = lambda: Settings(
        env="test",
        narrative_releases_enabled=True,
        narrative_release_builder_image_digest=build.builder_image_digest,
        narrative_release_toolchain_sha256=build.toolchain_sha256,
    )
    try:
        workspace = (await client.post("/v1/workspaces", json={"name": "Fenced build"})).json()
        headers = {"X-Tenant-ID": workspace["id"]}
        project = (
            await client.post(
                "/v1/narrative/projects",
                headers=headers,
                json={"name": "Original", "idempotency_key": str(uuid4())},
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
        scope = {
            "tenant_id": UUID(workspace["id"]),
            "release_id": UUID(release["id"]),
            "job_id": UUID(release["job"]["id"]),
        }
        yield client, factory, backend, headers, f"{path}/{release['id']}", scope, build
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.anyio
async def test_recovered_execution_fences_old_failure_and_same_token_replay(execution_case):
    client, factory, _, headers, item, scope, _build = execution_case
    first, replacement = uuid4(), uuid4()
    async with factory() as session:
        lease = await claim_release_execution(session, **scope, token=first)
        assert lease.acquired and lease.state.execution_token == first
        await session.commit()
    async with factory() as session:
        replay = await claim_release_execution(session, **scope, token=first)
        assert not replay.acquired
        await session.commit()
    async with factory() as session:
        lease = await claim_release_execution(session, **scope, token=replacement)
        assert lease.acquired and lease.state.execution_token == replacement
        await session.commit()
    async with factory() as session:
        assert not await finish_release_failure(
            session, **scope, token=first, error_code="engine_failed"
        )
        await session.commit()
    response = await client.get(item, headers=headers)
    assert response.json()["job"]["status"] == "running"
    assert str(replacement) not in response.text and str(first) not in response.text
    events = (await client.get(f"{item}/jobs/{scope['job_id']}/events", headers=headers)).json()
    assert [row["code"] for row in events] == [
        "release.queued",
        "release.running",
        "release.execution_replaced",
    ]
    async with factory() as session:
        assert await finish_release_failure(
            session, **scope, token=replacement, error_code="engine_timeout"
        )
        await session.commit()
    job = (await client.get(item, headers=headers)).json()["job"]
    assert job["status"] == "failed" and job["error_code"] == "engine_timeout"


@pytest.mark.anyio
async def test_running_cancellation_survives_recovery_without_a_builder(execution_case):
    client, factory, _, headers, item, scope, _build = execution_case
    original, replacement = uuid4(), uuid4()
    async with factory() as session:
        await claim_release_execution(session, **scope, token=original)
        await session.commit()
    assert (
        await client.post(f"{item}/jobs/{scope['job_id']}/cancel", headers=headers)
    ).status_code == 200
    app.dependency_overrides[get_settings] = lambda: Settings(env="test")
    async with factory() as session:
        recovered = await claim_release_execution(session, **scope, token=replacement)
        assert recovered.acquired and recovered.state.cancel_requested
        await session.commit()
    async with factory() as session:
        assert not await finish_release_failure(
            session, **scope, token=original, error_code="engine_failed"
        )
        assert await finish_release_failure(
            session, **scope, token=replacement, error_code="engine_failed"
        )
        assert not await finish_release_failure(
            session, **scope, token=replacement, error_code="engine_failed"
        )
        await session.commit()
    response = (await client.get(item, headers=headers)).json()
    assert response["job"]["status"] == "cancelled"
    assert response["job"]["error_code"] is None
    async with factory() as session:
        assert not (await claim_release_execution(session, **scope, token=uuid4())).acquired


@pytest.mark.anyio
async def test_old_cleanup_cannot_affect_an_explicit_retry(execution_case):
    client, factory, _, headers, item, scope, _build = execution_case
    token = uuid4()
    async with factory() as session:
        await claim_release_execution(session, **scope, token=token)
        assert await finish_release_failure(
            session, **scope, token=token, error_code="runtime_unavailable"
        )
        await session.commit()
    retried = await client.post(
        f"{item}/retry", headers=headers, json={"idempotency_key": str(uuid4())}
    )
    assert retried.status_code == 202
    assert retried.json()["job"]["id"] != str(scope["job_id"])
    async with factory() as session:
        assert not await finish_release_failure(
            session, **scope, token=token, error_code="worker_interrupted"
        )
        assert not (await claim_release_execution(session, **scope, token=uuid4())).acquired
        await session.commit()
    assert (await client.get(item, headers=headers)).json()["job"]["status"] == "queued"


@pytest.mark.anyio
async def test_unknown_manual_running_work_cannot_be_registered_or_supervised(execution_case):
    client, factory, _, headers, item, scope, _build = execution_case
    token, run = uuid4(), uuid4()
    async with factory() as session:
        await claim_release_execution(session, **scope, token=token)
        await session.commit()
    async with factory() as session:
        with pytest.raises(ReleaseInputError, match=r"^execution_registration_conflict$"):
            await register_release_workflow(session, **scope, workflow_run_id=run)
        assert await workflow_cleanup_plan(session, **scope, workflow_run_id=run) is None
        assert not await finalize_release_workflow(
            session, **scope, workflow_run_id=run, expected_token=token, expected_attempt=0
        )
        await session.commit()
    assert (await client.get(item, headers=headers)).json()["job"]["status"] == "running"
    async with factory() as session:
        assert await finish_release_failure(
            session, **scope, token=token, error_code="worker_interrupted"
        )
        await session.commit()


@pytest.mark.anyio
async def test_owner_pair_constraints_reject_partial_or_negative_identity(execution_case):
    _, factory, _, _, _, scope, _build = execution_case
    for run, attempt in [(None, 1), (uuid4(), None), (uuid4(), -1)]:
        async with factory() as session:
            with pytest.raises(IntegrityError):
                await session.execute(
                    update(NarrativeReleaseJob)
                    .where(
                        NarrativeReleaseJob.id == scope["job_id"],
                    )
                    .values(workflow_run_id=run, activity_attempt=attempt)
                )
            await session.rollback()


@pytest.mark.anyio
async def test_foreign_execution_scope_and_unreviewed_error_text_are_rejected(execution_case):
    client, factory, _, headers, item, scope, _build = execution_case
    async with factory() as session:
        with pytest.raises(NotFoundError):
            await claim_release_execution(session, **{**scope, "tenant_id": uuid4()}, token=uuid4())
        with pytest.raises(NotFoundError):
            await claim_release_execution(session, **{**scope, "job_id": uuid4()}, token=uuid4())
        with pytest.raises(ValueError, match=r"^Invalid release failure code$"):
            await finish_release_failure(
                session, **scope, token=uuid4(), error_code="PRIVATE_SOURCE_OR_PROVIDER_ERROR"
            )
        await session.rollback()
    assert (await client.get(item, headers=headers)).json()["job"]["status"] == "queued"


@pytest.mark.anyio
async def test_postgres_recoveries_serialize_and_only_one_owner_can_finish(execution_case):
    client, factory, backend, headers, item, scope, _build = execution_case
    if backend != "postgres":
        pytest.skip("Requires actual PostgreSQL release/job locks")
    async with factory() as session:
        await claim_release_execution(session, **scope, token=uuid4())
        await session.commit()
    tokens = [uuid4(), uuid4()]

    async def recover(token):
        async with factory() as session:
            result = await claim_release_execution(session, **scope, token=token)
            await session.commit()
            return result

    async with factory() as blocker:
        await blocker.scalar(
            select(NarrativeRelease)
            .where(NarrativeRelease.id == scope["release_id"])
            .with_for_update()
        )
        blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
        tasks = [asyncio.create_task(recover(token)) for token in tokens]
        try:
            async with asyncio.timeout(5):
                while True:
                    async with factory() as observer:
                        waiting = await observer.scalar(
                            text(
                                "WITH RECURSIVE waiting(pid) AS ("
                                "SELECT pid FROM pg_stat_activity WHERE datname=current_database() "
                                "AND :blocker=ANY(pg_blocking_pids(pid)) UNION "
                                "SELECT a.pid FROM pg_stat_activity a JOIN waiting w "
                                "ON w.pid=ANY(pg_blocking_pids(a.pid)) "
                                "WHERE a.datname=current_database()) "
                                "SELECT count(DISTINCT pid) FROM waiting"
                            ),
                            {"blocker": blocker_pid},
                        )
                    if waiting == 2:
                        break
                    await asyncio.sleep(0.02)
        finally:
            await blocker.rollback()
            results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
    assert all(result.acquired for result in results)
    finished = []
    for token in tokens:
        async with factory() as session:
            finished.append(
                await finish_release_failure(
                    session, **scope, token=token, error_code="engine_failed"
                )
            )
            await session.commit()
    assert sum(finished) == 1
    events = (await client.get(f"{item}/jobs/{scope['job_id']}/events", headers=headers)).json()
    assert [row["sequence"] for row in events] == [1, 2, 3, 4, 5]
    assert [row["code"] for row in events].count("release.failed") == 1


@pytest.mark.anyio
async def test_private_input_requires_current_fence_and_exact_pinned_builder(execution_case):
    client, factory, _, headers, item, scope, build = execution_case
    token, replacement = uuid4(), uuid4()
    async with factory() as session:
        await claim_release_execution(session, **scope, token=token)
        await session.commit()
    async with factory() as session:
        package = (await load_release_input(session, **scope, token=token, build=build)).package
        for field, wrong in {
            "builder_image_digest": "sha256:" + "c" * 64,
            "toolchain_sha256": "c" * 64,
            "compiler_version": "0.2.0",
            "runtime_version": "0.2.0",
            "godot_version": "4.8.0.stable",
        }.items():
            with pytest.raises(ReleaseInputError, match=r"^runtime_unavailable$"):
                await load_release_input(
                    session, **scope, token=token, build=replace(build, **{field: wrong})
                )
        assert (
            package.content_hash == (await client.get(item, headers=headers)).json()["package_hash"]
        )
        assert not package.assets
        await session.commit()
    async with factory() as session:
        await claim_release_execution(session, **scope, token=replacement)
        await session.commit()
    async with factory() as session:
        with pytest.raises(ReleaseInputError, match=r"^execution_stale$"):
            await load_release_input(session, **scope, token=token, build=build)
        with pytest.raises(ReleaseInputError, match=r"^runtime_unavailable$"):
            await load_release_input(session, **scope, token=replacement, build=None)
        assert await finish_release_failure(
            session, **scope, token=replacement, error_code="runtime_unavailable"
        )
        await session.commit()
    assert (await client.get(item, headers=headers)).json()["job"]["status"] == "failed"


@pytest.mark.anyio
async def test_cancelled_input_is_denied_before_missing_builder_resolution(execution_case):
    client, factory, _, headers, item, scope, _build = execution_case
    token = uuid4()
    async with factory() as session:
        await claim_release_execution(session, **scope, token=token)
        await session.commit()
    await client.post(f"{item}/jobs/{scope['job_id']}/cancel", headers=headers)
    async with factory() as session:
        with pytest.raises(ReleaseInputError, match=r"^execution_cancelled$"):
            await load_release_input(session, **scope, token=token, build=None)
        assert await finish_release_failure(session, **scope, token=token, cancelled=True)
        await session.commit()
    assert (await client.get(item, headers=headers)).json()["job"]["status"] == "cancelled"


@pytest.mark.anyio
async def test_workflow_registration_is_independent_and_required_before_build_claim(execution_case):
    client, factory, _, headers, item, scope, _build = execution_case
    run, token = uuid4(), uuid4()
    async with factory() as session:
        with pytest.raises(ReleaseInputError, match=r"^execution_registration_pending$"):
            await claim_release_execution(
                session, **scope, token=token, workflow_run_id=run, activity_attempt=1
            )
        assert await register_release_workflow(session, **scope, workflow_run_id=run)
        assert not await register_release_workflow(session, **scope, workflow_run_id=run)
        await session.commit()
    async with factory() as session:
        assert not (await claim_release_execution(session, **scope, token=uuid4())).acquired
        assert not (
            await claim_release_execution(
                session, **scope, token=uuid4(), workflow_run_id=uuid4(), activity_attempt=1
            )
        ).acquired
        claim = await claim_release_execution(
            session, **scope, token=token, workflow_run_id=run, activity_attempt=1
        )
        assert claim.acquired
        await session.commit()
    metadata = await client.get(item, headers=headers)
    assert metadata.json()["job"]["status"] == "running" and str(run) not in metadata.text


@pytest.mark.anyio
async def test_late_lower_attempt_and_stale_supervisor_cannot_take_a_newer_execution(
    execution_case,
):
    client, factory, _, headers, item, scope, _build = execution_case
    run, first, newer = uuid4(), uuid4(), uuid4()
    async with factory() as session:
        await register_release_workflow(session, **scope, workflow_run_id=run)
        await claim_release_execution(
            session, **scope, token=first, workflow_run_id=run, activity_attempt=2
        )
        await session.commit()
    async with factory() as session:
        assert not (
            await claim_release_execution(
                session, **scope, token=uuid4(), workflow_run_id=run, activity_attempt=1
            )
        ).acquired
        assert (
            await claim_release_execution(
                session, **scope, token=newer, workflow_run_id=run, activity_attempt=3
            )
        ).acquired
        await session.commit()
    async with factory() as session:
        assert await workflow_cleanup_plan(session, **scope, workflow_run_id=uuid4()) is None
        plan = await workflow_cleanup_plan(session, **scope, workflow_run_id=run)
        assert plan.execution_token == newer and plan.activity_attempt == 3
        assert not await finalize_release_workflow(
            session, **scope, workflow_run_id=run, expected_token=first, expected_attempt=2
        )
        assert await finalize_release_workflow(
            session, **scope, workflow_run_id=run, expected_token=newer, expected_attempt=3
        )
        await session.commit()
    assert (await client.get(item, headers=headers)).json()["job"]["status"] == "failed"


@pytest.mark.anyio
async def test_registered_job_can_fail_after_all_activities_exhaust_before_first_claim(
    execution_case,
):
    client, factory, _, headers, item, scope, _build = execution_case
    run = uuid4()
    async with factory() as session:
        await register_release_workflow(session, **scope, workflow_run_id=run)
        await session.commit()
    async with factory() as session:
        plan = await workflow_cleanup_plan(session, **scope, workflow_run_id=run)
        assert plan.execution_token is None and plan.activity_attempt == 0
        assert await finalize_release_workflow(
            session, **scope, workflow_run_id=run, expected_token=None, expected_attempt=0
        )
        await session.commit()
    job = (await client.get(item, headers=headers)).json()["job"]
    assert job["status"] == "failed" and job["error_code"] == "worker_interrupted"
    retried = await client.post(
        item + "/retry", headers=headers, json={"idempotency_key": str(uuid4())}
    )
    assert retried.status_code == 202
    async with factory() as session:
        assert not await finalize_release_workflow(
            session, **scope, workflow_run_id=run, expected_token=None, expected_attempt=0
        )
        await session.commit()
    assert (await client.get(item, headers=headers)).json()["job"]["status"] == "queued"
