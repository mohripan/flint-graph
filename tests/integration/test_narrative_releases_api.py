"""Durable authorized release commands, without claiming an engine build from mocks."""

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError

from flint_graph.api.dependencies import get_session
from flint_graph.application.services.audit import AuditActor
from flint_graph.application.services.narrative_projects import archive_project, create_revision
from flint_graph.config import Settings, get_settings
from flint_graph.domain.enums import WorkspaceMembershipStatus
from flint_graph.infrastructure.db.models import (
    NarrativeProject,
    NarrativeRelease,
    NarrativeReleaseJob,
    OutboxMessage,
    Tenant,
    User,
    WorkspaceMembership,
)
from flint_graph.main import app


@pytest.fixture
def release_configuration(narrative_env):
    # Synthetic operator configuration only; real toolchain/child proof is separate.
    settings = Settings(
        env="test",
        narrative_releases_enabled=True,
        narrative_release_builder_image_digest="sha256:" + "a" * 64,
        narrative_release_toolchain_sha256="b" * 64,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    yield settings
    app.dependency_overrides.pop(get_settings, None)


@pytest.mark.anyio
async def test_release_pins_a_saved_revision_and_replays_even_when_builder_is_disabled(
    narrative_env, release_configuration
):
    client, _, _ = narrative_env
    workspace = (await client.post("/v1/workspaces", json={"name": "Release authors"})).json()
    headers = {"X-Tenant-ID": workspace["id"]}
    project = (
        await client.post(
            "/v1/narrative/projects",
            headers=headers,
            json={"name": "A downloadable story", "idempotency_key": str(uuid4())},
        )
    ).json()
    path = f"/v1/narrative/projects/{project['id']}"
    revision = (
        await client.get(f"{path}/revisions/{project['head_revision_id']}", headers=headers)
    ).json()
    request = {"revision_id": revision["id"], "idempotency_key": str(uuid4())}

    created = await client.post(f"{path}/releases", headers=headers, json=request)

    assert created.status_code == 202
    release = created.json()
    assert release["revision_id"] == revision["id"]
    assert release["package_hash"] == revision["content_hash"]
    assert release["job"]["status"] == "queued"
    assert release["job"]["attempt_number"] == 1
    assert release["job"]["cancel_requested"] is False
    assert release["build_identity"]["builder_image_digest"] == "sha256:" + "a" * 64
    assert "story_json" not in release
    assert "object_key" not in created.text
    app.dependency_overrides[get_settings] = lambda: Settings(env="test")
    replay = await client.post(f"{path}/releases", headers=headers, json=request)
    assert replay.status_code == 202
    assert replay.json() == release
    changed_intent = await client.post(
        f"{path}/releases", headers=headers, json={**request, "revision_id": str(uuid4())}
    )
    assert changed_intent.status_code == 409
    listed = await client.get(f"{path}/releases", headers=headers)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [release["id"]]
    assert (await client.get(path, headers=headers)).json()["head_revision_id"] == revision["id"]


async def new_story(client, name="Release fixture", auth=None):
    workspace = (await client.post("/v1/workspaces", headers=auth, json={"name": name})).json()
    headers = {**(auth or {}), "X-Tenant-ID": workspace["id"]}
    project = (
        await client.post(
            "/v1/narrative/projects",
            headers=headers,
            json={"name": name, "idempotency_key": str(uuid4())},
        )
    ).json()
    return headers, project, f"/v1/narrative/projects/{project['id']}"


@pytest.mark.anyio
async def test_queued_cancel_and_explicit_retry_keep_the_original_acceptance_identity(
    narrative_env, release_configuration
):
    client, _, _ = narrative_env
    headers, project, path = await new_story(client)
    request = {"revision_id": project["head_revision_id"], "idempotency_key": str(uuid4())}
    release = (await client.post(f"{path}/releases", headers=headers, json=request)).json()
    item = f"{path}/releases/{release['id']}"
    first_job = release["job"]["id"]
    cancelled = await client.post(f"{item}/jobs/{first_job}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancel_requested"] is True
    assert (
        await client.post(f"{item}/jobs/{first_job}/cancel", headers=headers)
    ).json() == cancelled.json()
    retry_request = {"idempotency_key": str(uuid4())}
    retry = await client.post(f"{item}/retry", headers=headers, json=retry_request)
    assert retry.status_code == 202
    assert retry.json()["id"] == release["id"]
    assert retry.json()["job"]["id"] != first_job
    assert retry.json()["job"]["attempt_number"] == 2
    assert retry.json()["job"]["status"] == "queued"
    app.dependency_overrides[get_settings] = lambda: Settings(env="test")
    assert (
        await client.post(f"{item}/retry", headers=headers, json=retry_request)
    ).json() == retry.json()
    replay = await client.post(f"{path}/releases", headers=headers, json=request)
    assert replay.json()["job"]["id"] == first_job
    assert replay.json()["job"]["status"] == "cancelled"
    assert (await client.get(item, headers=headers)).json()["job"]["id"] == retry.json()["job"][
        "id"
    ]
    jobs = await client.get(f"{item}/jobs", headers=headers)
    assert [row["attempt_number"] for row in jobs.json()] == [2, 1]
    assert (
        await client.post(
            f"{path}/archive",
            headers=headers,
            json={"base_revision_id": project["head_revision_id"], "archived": True},
        )
    ).status_code == 200
    archived_replay = await client.post(f"{item}/retry", headers=headers, json=retry_request)
    assert archived_replay.status_code == 202
    assert archived_replay.json()["job"]["id"] == retry.json()["job"]["id"]


@pytest.mark.anyio
async def test_release_pages_do_not_repeat_a_same_timestamp_cursor(
    narrative_env, release_configuration
):
    client, _, _ = narrative_env
    headers, project, path = await new_story(client)
    ids = set()
    for _ in range(2):
        row = await client.post(
            f"{path}/releases",
            headers=headers,
            json={"revision_id": project["head_revision_id"], "idempotency_key": str(uuid4())},
        )
        assert row.status_code == 202
        ids.add(row.json()["id"])
    first = (await client.get(f"{path}/releases?limit=1", headers=headers)).json()
    second = (
        await client.get(f"{path}/releases?limit=1&before_id={first[0]['id']}", headers=headers)
    ).json()
    assert len(first) == len(second) == 1
    assert first[0]["id"] != second[0]["id"]
    assert {first[0]["id"], second[0]["id"]} == ids
    last = await client.get(f"{path}/releases?before_id={second[0]['id']}", headers=headers)
    assert last.json() == []


@pytest.mark.anyio
async def test_running_cancel_is_a_durable_request_until_the_fenced_worker_finishes(
    narrative_env, release_configuration
):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    release = (
        await client.post(
            f"{path}/releases",
            headers=headers,
            json={"revision_id": project["head_revision_id"], "idempotency_key": str(uuid4())},
        )
    ).json()
    job_id = release["job"]["id"]
    item = f"{path}/releases/{release['id']}/jobs/{job_id}"
    # Arrange an external worker's running state; this test does not execute an engine.
    async with factory() as session:
        job = await session.get(NarrativeReleaseJob, UUID(job_id))
        job.status, job.execution_token = "running", uuid4()
        await session.commit()
    pending = await client.post(f"{item}/cancel", headers=headers)
    assert pending.status_code == 200
    assert pending.json()["status"] == "running"
    assert pending.json()["cancel_requested"] is True
    assert "execution_token" not in pending.text
    first = await client.get(f"{item}/events", headers=headers)
    assert first.status_code == 200
    assert [row["code"] for row in first.json()] == ["release.queued", "release.cancel_requested"]
    assert [row["sequence"] for row in first.json()] == [1, 2]
    assert (await client.post(f"{item}/cancel", headers=headers)).json() == pending.json()
    assert (await client.get(f"{item}/events", headers=headers)).json() == first.json()
    assert (
        len((await client.get(f"{item}/events?after_sequence=1&limit=1", headers=headers)).json())
        == 1
    )
    async with factory() as session:
        messages = list(
            await session.scalars(
                select(OutboxMessage).where(OutboxMessage.aggregate_id == UUID(job_id))
            )
        )
    assert sorted(row.topic for row in messages) == [
        "narrative.release_cancelled",
        "narrative.release_queued",
    ]


@pytest.mark.anyio
async def test_retry_keeps_the_pinned_runtime_and_replays_its_own_attempt_after_config_changes(
    narrative_env, release_configuration
):
    client, _, _ = narrative_env
    headers, project, path = await new_story(client)
    release = (
        await client.post(
            f"{path}/releases",
            headers=headers,
            json={"revision_id": project["head_revision_id"], "idempotency_key": str(uuid4())},
        )
    ).json()
    item = f"{path}/releases/{release['id']}"
    await client.post(f"{item}/jobs/{release['job']['id']}/cancel", headers=headers)
    request = {"idempotency_key": str(uuid4())}
    release_configuration.narrative_release_builder_image_digest = "sha256:" + "c" * 64
    assert (await client.post(f"{item}/retry", headers=headers, json=request)).status_code == 503
    assert len((await client.get(f"{item}/jobs", headers=headers)).json()) == 1
    release_configuration.narrative_release_builder_image_digest = "sha256:" + "a" * 64
    retried = await client.post(f"{item}/retry", headers=headers, json=request)
    assert retried.status_code == 202
    assert retried.json()["build_identity"] == release["build_identity"]
    second_job = retried.json()["job"]["id"]
    assert (
        await client.post(f"{item}/retry", headers=headers, json={"idempotency_key": str(uuid4())})
    ).status_code == 409
    await client.post(f"{item}/jobs/{second_job}/cancel", headers=headers)
    release_configuration.narrative_releases_enabled = False
    replay = await client.post(f"{item}/retry", headers=headers, json=request)
    assert replay.status_code == 202
    assert replay.json()["job"]["id"] == second_job
    assert replay.json()["job"]["status"] == "cancelled"
    assert (
        await client.post(f"{item}/retry", headers=headers, json={"idempotency_key": str(uuid4())})
    ).status_code == 503
    assert len((await client.get(f"{item}/jobs", headers=headers)).json()) == 2


@pytest.mark.anyio
async def test_completed_attempt_is_not_cancelled_or_retried_in_place(
    narrative_env, release_configuration
):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    release = (
        await client.post(
            f"{path}/releases",
            headers=headers,
            json={"revision_id": project["head_revision_id"], "idempotency_key": str(uuid4())},
        )
    ).json()
    item = f"{path}/releases/{release['id']}"
    async with factory() as session:
        job = await session.get(NarrativeReleaseJob, UUID(release["job"]["id"]))
        job.status = "completed"  # Arrange an external publisher's terminal state only.
        await session.commit()
    cancelled = await client.post(f"{item}/jobs/{release['job']['id']}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "completed"
    assert cancelled.json()["cancel_requested"] is False
    assert (
        await client.post(f"{item}/retry", headers=headers, json={"idempotency_key": str(uuid4())})
    ).status_code == 409
    assert len((await client.get(f"{item}/jobs", headers=headers)).json()) == 1


@pytest.mark.anyio
async def test_release_event_cursor_stays_within_the_database_integer_boundary(
    narrative_env, release_configuration
):
    client, _, _ = narrative_env
    headers, project, path = await new_story(client)
    release = (
        await client.post(
            f"{path}/releases",
            headers=headers,
            json={"revision_id": project["head_revision_id"], "idempotency_key": str(uuid4())},
        )
    ).json()
    item = f"{path}/releases/{release['id']}/jobs/{release['job']['id']}/events"
    for value in [-1, 2**31, 10**100]:
        assert (
            await client.get(f"{item}?after_sequence={value}", headers=headers)
        ).status_code == 422
    accepted = await client.get(f"{item}?after_sequence={2**31 - 1}", headers=headers)
    assert accepted.status_code == 200
    assert accepted.json() == []


@pytest.mark.anyio
async def test_attempt_reads_cancel_retry_and_events_apply_signed_membership_and_scope(
    narrative_env, oidc_auth
):
    client, factory, _ = narrative_env
    configured = app.dependency_overrides[get_settings]().model_copy(
        update={
            "narrative_releases_enabled": True,
            "narrative_release_builder_image_digest": "sha256:" + "a" * 64,
            "narrative_release_toolchain_sha256": "b" * 64,
        }
    )
    app.dependency_overrides[get_settings] = lambda: configured
    owner = {"Authorization": "Bearer " + oidc_auth("attempt-owner")}
    headers, project, path = await new_story(client, auth=owner)
    added = await client.post(
        f"/v1/workspaces/{project['tenant_id']}/members",
        headers=owner,
        json={
            "oidc_issuer": "https://keycloak.example/realms/flintgraph",
            "oidc_subject": "attempt-viewer",
            "role": "viewer",
        },
    )
    assert added.status_code == 201
    viewer = {**headers, "Authorization": "Bearer " + oidc_auth("attempt-viewer")}
    release = (
        await client.post(
            f"{path}/releases",
            headers=headers,
            json={"revision_id": project["head_revision_id"], "idempotency_key": str(uuid4())},
        )
    ).json()
    item = f"{path}/releases/{release['id']}"
    job = f"{item}/jobs/{release['job']['id']}"
    reads = [item, f"{item}/jobs", job, f"{job}/events"]
    for read in reads:
        assert (await client.get(read, headers=viewer)).status_code == 200
    assert (await client.post(f"{job}/cancel", headers=viewer)).status_code == 403
    assert (
        await client.post(f"{item}/retry", headers=viewer, json={"idempotency_key": str(uuid4())})
    ).status_code == 403
    foreign_headers, foreign, foreign_path = await new_story(
        client, name="Foreign attempts", auth=owner
    )
    other = (
        await client.post(
            f"{foreign_path}/releases",
            headers=foreign_headers,
            json={"revision_id": foreign["head_revision_id"], "idempotency_key": str(uuid4())},
        )
    ).json()
    foreign_job = f"{item}/jobs/{other['job']['id']}"
    foreign_release = f"{path}/releases/{other['id']}"
    assert (await client.get(foreign_release, headers=headers)).status_code == 404
    assert (await client.get(foreign_release + "/jobs", headers=headers)).status_code == 404
    assert (
        await client.post(
            foreign_release + "/retry", headers=headers, json={"idempotency_key": str(uuid4())}
        )
    ).status_code == 404
    assert (await client.get(foreign_job, headers=headers)).status_code == 404
    assert (await client.get(f"{foreign_job}/events", headers=headers)).status_code == 404
    assert (await client.post(f"{foreign_job}/cancel", headers=headers)).status_code == 404
    assert (
        await client.get(f"{item}/jobs?before_id={other['job']['id']}", headers=headers)
    ).status_code == 404
    assert (
        await client.post(
            f"{path}/archive",
            headers=headers,
            json={"base_revision_id": project["head_revision_id"], "archived": True},
        )
    ).status_code == 200
    for read in reads:
        assert (await client.get(read, headers=viewer)).status_code == 404
        assert (
            await client.get(read + "?include_archived=true", headers=viewer)
        ).status_code == 200
    assert (await client.post(f"{job}/cancel", headers=headers)).json()["status"] == "cancelled"
    assert (
        await client.post(f"{item}/retry", headers=headers, json={"idempotency_key": str(uuid4())})
    ).status_code == 409
    async with factory() as session:
        viewer_id = await session.scalar(
            select(User.id).where(User.oidc_subject == "attempt-viewer")
        )
        await session.execute(
            update(WorkspaceMembership)
            .where(
                WorkspaceMembership.tenant_id == UUID(project["tenant_id"]),
                WorkspaceMembership.user_id == viewer_id,
            )
            .values(status=WorkspaceMembershipStatus.DISABLED)
        )
        await session.commit()
    for read in reads:
        assert (
            await client.get(read + "?include_archived=true", headers=viewer)
        ).status_code == 403
    assert (
        await client.get(item, headers={"X-Tenant-ID": project["tenant_id"]})
    ).status_code == 401


@pytest.mark.anyio
async def test_release_queue_commit_failure_is_private_and_retry_keeps_one_durable_intent(
    narrative_env, release_configuration
):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    request = {"revision_id": project["head_revision_id"], "idempotency_key": str(uuid4())}
    fail = True

    async def sessions():
        async with factory() as session:
            real_commit = session.commit

            async def commit():
                nonlocal fail
                if fail:
                    fail = False
                    raise SQLAlchemyError("synthetic-private-release-canary")
                await real_commit()

            session.commit = commit
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = sessions
    failed = await client.post(f"{path}/releases", headers=headers, json=request)
    assert failed.status_code == 503
    assert "synthetic-private-release-canary" not in failed.text
    assert (await client.get(f"{path}/releases", headers=headers)).json() == []
    retried = await client.post(f"{path}/releases", headers=headers, json=request)
    assert retried.status_code == 202
    async with factory() as session:
        messages = list(
            await session.scalars(
                select(OutboxMessage).where(OutboxMessage.topic == "narrative.release_queued")
            )
        )
    assert len(messages) == 1
    assert messages[0].payload == {
        "schema_version": "1",
        "tenant_id": project["tenant_id"],
        "release_id": retried.json()["id"],
        "job_id": retried.json()["job"]["id"],
    }
    assert "story_json" not in str(messages[0].payload)


@pytest.mark.anyio
async def test_release_admission_limit_does_not_break_an_accepted_key_replay(
    narrative_env, release_configuration
):
    client, _, _ = narrative_env
    release_configuration.narrative_release_max_active_jobs_per_workspace = 1
    headers, project, path = await new_story(client)
    request = {"revision_id": project["head_revision_id"], "idempotency_key": str(uuid4())}
    first = await client.post(f"{path}/releases", headers=headers, json=request)
    assert first.status_code == 202
    assert (
        await client.post(f"{path}/releases", headers=headers, json=request)
    ).json() == first.json()
    refused = await client.post(
        f"{path}/releases", headers=headers, json={**request, "idempotency_key": str(uuid4())}
    )
    assert refused.status_code == 429
    assert len((await client.get(f"{path}/releases", headers=headers)).json()) == 1


@pytest.mark.anyio
async def test_signed_roles_foreign_revisions_and_archives_bound_release_commands(
    narrative_env, oidc_auth
):
    client, _, _ = narrative_env
    configured = app.dependency_overrides[get_settings]().model_copy(
        update={
            "narrative_releases_enabled": True,
            "narrative_release_builder_image_digest": "sha256:" + "a" * 64,
            "narrative_release_toolchain_sha256": "b" * 64,
        }
    )
    app.dependency_overrides[get_settings] = lambda: configured
    owner = {"Authorization": "Bearer " + oidc_auth("release-owner")}
    headers, project, path = await new_story(client, auth=owner)
    added = await client.post(
        f"/v1/workspaces/{project['tenant_id']}/members",
        headers=owner,
        json={
            "oidc_issuer": "https://keycloak.example/realms/flintgraph",
            "oidc_subject": "release-viewer",
            "role": "viewer",
        },
    )
    assert added.status_code == 201
    viewer = {**headers, "Authorization": "Bearer " + oidc_auth("release-viewer")}
    request = {"revision_id": project["head_revision_id"], "idempotency_key": str(uuid4())}
    assert (await client.post(f"{path}/releases", headers=viewer, json=request)).status_code == 403
    accepted = await client.post(f"{path}/releases", headers=headers, json=request)
    assert accepted.status_code == 202
    assert len((await client.get(f"{path}/releases", headers=viewer)).json()) == 1
    _, foreign, foreign_path = await new_story(client, name="Foreign release", auth=owner)
    assert (await client.get(f"{foreign_path}/releases", headers=headers)).status_code == 404
    foreign_revision = await client.post(
        f"{path}/releases",
        headers=headers,
        json={"revision_id": foreign["head_revision_id"], "idempotency_key": str(uuid4())},
    )
    assert foreign_revision.status_code == 404
    outsider = {**headers, "Authorization": "Bearer " + oidc_auth("release-outsider")}
    assert (await client.get(f"{path}/releases", headers=outsider)).status_code == 403
    assert (
        await client.post(
            f"{path}/archive",
            headers=headers,
            json={"base_revision_id": project["head_revision_id"], "archived": True},
        )
    ).status_code == 200
    assert (await client.get(f"{path}/releases", headers=viewer)).status_code == 404
    assert (
        len((await client.get(f"{path}/releases?include_archived=true", headers=viewer)).json())
        == 1
    )
    assert (await client.post(f"{path}/releases", headers=headers, json=request)).status_code == 202
    assert (
        await client.post(
            f"{path}/releases", headers=headers, json={**request, "idempotency_key": str(uuid4())}
        )
    ).status_code == 409


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["save", "archive"])
async def test_postgres_project_writer_and_release_admission_do_not_deadlock(
    narrative_env, release_configuration, operation
):
    client, factory, backend = narrative_env
    if backend != "postgres":
        pytest.skip("Requires the explicitly owned PostgreSQL locking boundary")
    headers, project, path = await new_story(client)
    base = (
        await client.get(f"{path}/revisions/{project['head_revision_id']}", headers=headers)
    ).json()
    pending = None
    async with factory() as writer:
        await writer.scalar(
            select(NarrativeProject)
            .where(NarrativeProject.id == UUID(project["id"]))
            .with_for_update()
        )
        writer_pid = await writer.scalar(text("SELECT pg_backend_pid()"))
        try:
            pending = asyncio.create_task(
                client.post(
                    f"{path}/releases",
                    headers=headers,
                    json={"revision_id": base["id"], "idempotency_key": str(uuid4())},
                )
            )
            async with asyncio.timeout(5):
                while True:
                    async with factory() as observer:
                        blocked = await observer.scalar(
                            text(
                                "SELECT count(*) FROM pg_stat_activity "
                                "WHERE datname=current_database() AND wait_event_type='Lock' "
                                "AND :writer_pid=ANY(pg_blocking_pids(pid))"
                            ),
                            {"writer_pid": writer_pid},
                        )
                    if blocked:
                        break
                    await asyncio.sleep(0.02)
            common = {
                "tenant_id": UUID(project["tenant_id"]),
                "project_id": UUID(project["id"]),
                "base_revision_id": UUID(base["id"]),
                "actor": AuditActor(user_id=UUID(base["author_user_id"])),
            }
            async with asyncio.timeout(5):
                if operation == "save":
                    await create_revision(
                        writer,
                        **common,
                        author_user_id=UUID(base["author_user_id"]),
                        idempotency_key=uuid4(),
                        story_json=base["story_json"],
                        notices="Saved while release admission waited.",
                    )
                else:
                    await archive_project(writer, **common, archived=True)
                await writer.commit()
        finally:
            await writer.rollback()
            if pending:
                result = await asyncio.wait_for(pending, timeout=10)
    assert result.status_code == (202 if operation == "save" else 409)


@pytest.mark.anyio
async def test_creation_key_replay_preserves_its_original_attempt_after_a_worker_retry(
    narrative_env, release_configuration
):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    request = {"revision_id": project["head_revision_id"], "idempotency_key": str(uuid4())}
    original = (await client.post(f"{path}/releases", headers=headers, json=request)).json()
    # Arrange the trusted worker/retry side of this public create-replay boundary.
    # The explicit retry command's own transport tests follow its implementation.
    async with factory() as session:
        job = await session.get(NarrativeReleaseJob, UUID(original["job"]["id"]))
        job.status = "failed"
        await session.flush()
        session.add(
            NarrativeReleaseJob(
                id=uuid4(),
                tenant_id=UUID(project["tenant_id"]),
                project_id=UUID(project["id"]),
                release_id=UUID(original["id"]),
                attempt_number=2,
                retry_key=uuid4(),
                status="queued",
            )
        )
        await session.commit()
    replay = await client.post(f"{path}/releases", headers=headers, json=request)
    assert replay.status_code == 202
    assert replay.json()["job"]["id"] == original["job"]["id"]
    assert replay.json()["job"]["attempt_number"] == 1
    assert (await client.get(f"{path}/releases", headers=headers)).json()[0]["job"][
        "attempt_number"
    ] == 2


@pytest.mark.anyio
async def test_postgres_release_identity_is_immutable_and_foreign_revision_fk_is_enforced(
    narrative_env, release_configuration
):
    client, factory, backend = narrative_env
    if backend != "postgres":
        pytest.skip("Requires actual migration triggers and composite PostgreSQL FK")
    headers, project, path = await new_story(client)
    release = (
        await client.post(
            f"{path}/releases",
            headers=headers,
            json={"revision_id": project["head_revision_id"], "idempotency_key": str(uuid4())},
        )
    ).json()
    async with factory() as session:
        with pytest.raises(DBAPIError) as rejected:
            await session.execute(
                update(NarrativeRelease)
                .where(NarrativeRelease.id == UUID(release["id"]))
                .values(package_hash="c" * 64)
            )
        assert rejected.value.orig.sqlstate == "55000"
        await session.rollback()
    _, foreign, _ = await new_story(client, name="Other release identity")
    async with factory() as session:
        original = await session.get(NarrativeRelease, UUID(release["id"]))
        candidate = NarrativeRelease(
            id=uuid4(),
            tenant_id=UUID(foreign["tenant_id"]),
            project_id=UUID(foreign["id"]),
            revision_id=original.revision_id,
            creation_key=uuid4(),
            request_hash=original.request_hash,
            package_hash=original.package_hash,
            compiler_version=original.compiler_version,
            runtime_version=original.runtime_version,
            godot_version=original.godot_version,
            toolchain_sha256=original.toolchain_sha256,
            builder_image_digest=original.builder_image_digest,
            creator_user_id=original.creator_user_id,
        )
        session.add(candidate)
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


@pytest.mark.anyio
async def test_postgres_concurrent_release_admissions_share_the_workspace_limit(
    narrative_env, oidc_auth
):
    client, factory, backend = narrative_env
    if backend != "postgres":
        pytest.skip("Requires the actual workspace admission lock")
    configured = app.dependency_overrides[get_settings]().model_copy(
        update={
            "narrative_releases_enabled": True,
            "narrative_release_max_active_jobs_per_workspace": 1,
            "narrative_release_builder_image_digest": "sha256:" + "a" * 64,
            "narrative_release_toolchain_sha256": "b" * 64,
        }
    )
    app.dependency_overrides[get_settings] = lambda: configured
    owner = {"Authorization": "Bearer " + oidc_auth("release-admission-owner")}
    headers, project, path = await new_story(client, auth=owner)
    writers = []
    for subject in ["release-admit-one", "release-admit-two"]:
        assert (
            await client.post(
                f"/v1/workspaces/{project['tenant_id']}/members",
                headers=owner,
                json={
                    "oidc_issuer": "https://keycloak.example/realms/flintgraph",
                    "oidc_subject": subject,
                    "role": "member",
                },
            )
        ).status_code == 201
        actor = {**headers, "Authorization": "Bearer " + oidc_auth(subject)}
        assert (await client.get(path, headers=actor)).status_code == 200
        writers.append(actor)
    tasks = []
    async with factory() as blocker:
        await blocker.scalar(
            select(Tenant)
            .where(Tenant.id == UUID(project["tenant_id"]))
            .with_for_update(key_share=True)
        )
        blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
        try:
            tasks = [
                asyncio.create_task(
                    client.post(
                        f"{path}/releases",
                        headers=actor,
                        json={
                            "revision_id": project["head_revision_id"],
                            "idempotency_key": str(uuid4()),
                        },
                    )
                )
                for actor in writers
            ]
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
            replies = await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
    assert sorted(reply.status_code for reply in replies) == [202, 429]
    assert len((await client.get(f"{path}/releases", headers=headers)).json()) == 1
