"""Worker fencing through persisted transitions and public inspection APIs."""

import asyncio
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from flint_graph.application.services.narrative_release_execution import (
    ReleaseInputError,
    claim_release_execution,
    finish_release_failure,
    load_release_input,
)
from flint_graph.application.services.narrative_releases import BuildIdentity
from flint_graph.config import Settings, get_settings
from flint_graph.domain.errors import NotFoundError
from flint_graph.infrastructure.db.models import NarrativeRelease
from flint_graph.main import app


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
        package = await load_release_input(session, **scope, token=token, build=build)
        for field, wrong in {
            "builder_image_digest": "sha256:" + "c" * 64,
            "toolchain_sha256": "c" * 64,
            "compiler_version": "0.2.0",
            "runtime_version": "0.3.0",
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
