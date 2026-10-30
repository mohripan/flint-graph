"""Atomic publication and signed membership downloads; engine qualification is separate."""

import asyncio
import hashlib
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text, update

from flint_graph.api.dependencies import get_narrative_artifact_store
from flint_graph.application.services.narrative_release_execution import claim_release_execution
from flint_graph.application.services.narrative_release_publication import (
    make_release_manifest,
    publish_release_artifacts,
)
from flint_graph.config import get_settings
from flint_graph.domain.enums import WorkspaceMembershipStatus
from flint_graph.infrastructure.db.models import NarrativeRelease, WorkspaceMembership
from flint_graph.infrastructure.narrative_artifact_store import (
    ArtifactStoreError,
    ObjectReceipt,
    release_artifact_key,
)
from flint_graph.main import app


class VerifiedFixtureStore:
    def __init__(self):
        self.objects = {}
        self.calls = []
        self.fail = False

    async def get_verified(self, key, *, expected_size, expected_sha256, max_bytes):
        self.calls.append(key)
        if self.fail:
            raise ArtifactStoreError("artifact_integrity")
        data = self.objects[key]
        assert len(data) == expected_size <= max_bytes
        assert hashlib.sha256(data).hexdigest() == expected_sha256
        return data


@pytest.fixture
async def publication_env(narrative_env, oidc_auth):
    client, factory, backend = narrative_env
    configured = app.dependency_overrides[get_settings]().model_copy(
        update={
            "narrative_releases_enabled": True,
            "narrative_release_builder_image_digest": "sha256:" + "a" * 64,
            "narrative_release_toolchain_sha256": "b" * 64,
        }
    )
    app.dependency_overrides[get_settings] = lambda: configured
    store = VerifiedFixtureStore()
    app.dependency_overrides[get_narrative_artifact_store] = lambda: store
    auth = {"Authorization": "Bearer " + oidc_auth("publication-owner")}
    try:
        workspace = (
            await client.post("/v1/workspaces", headers=auth, json={"name": "Published games"})
        ).json()
        headers = {**auth, "X-Tenant-ID": workspace["id"]}
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
        yield SimpleNamespace(
            client=client,
            factory=factory,
            backend=backend,
            headers=headers,
            item=f"{path}/{release['id']}",
            scope=scope,
            store=store,
            auth=oidc_auth,
            project=project,
        )
    finally:
        app.dependency_overrides.pop(get_narrative_artifact_store, None)


async def prepared(case, token, *, claim=True):
    async with case.factory() as session:
        if claim:
            await claim_release_execution(session, **case.scope, token=token)
            await session.commit()
        release = await session.get(NarrativeRelease, case.scope["release_id"])
        receipts = {}
        for kind, data in {"source": b"owned source fixture", "web": b"owned web fixture"}.items():
            key = release_artifact_key(**case.scope, execution_token=token, kind=kind)
            case.store.objects[key] = data
            receipts[kind] = ObjectReceipt(key, hashlib.sha256(data).hexdigest(), len(data))
        manifest = make_release_manifest(
            release, job_id=case.scope["job_id"], source=receipts["source"], web=receipts["web"]
        )
        key = release_artifact_key(**case.scope, execution_token=token, kind="manifest")
        case.store.objects[key] = manifest
        receipts["manifest"] = ObjectReceipt(
            key, hashlib.sha256(manifest).hexdigest(), len(manifest)
        )
        return receipts, manifest


@pytest.mark.anyio
async def test_only_atomic_completed_publication_exposes_verified_attachment_downloads(
    publication_env,
):
    case, token = publication_env, uuid4()
    url = case.item + "/artifacts/source"
    assert (await case.client.get(url, headers=case.headers)).status_code == 404
    receipts, manifest = await prepared(case, token)
    assert (await case.client.get(url, headers=case.headers)).status_code == 404
    async with case.factory() as session:
        result = await publish_release_artifacts(
            session, **case.scope, token=token, receipts=receipts, manifest_json=manifest
        )
        assert result.changed and result.status == "completed"
        await session.commit()
    metadata = await case.client.get(case.item, headers=case.headers)
    assert metadata.json()["job"]["status"] == "completed"
    assert {row["kind"] for row in metadata.json()["artifacts"]} == {"source", "web", "manifest"}
    assert "object_key" not in metadata.text and str(token) not in metadata.text
    for kind in receipts:
        response = await case.client.get(case.item + "/artifacts/" + kind, headers=case.headers)
        assert response.status_code == 200
        assert response.content == case.store.objects[receipts[kind].key]
        assert response.headers["content-disposition"].startswith("attachment;")
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-content-type-options"] == "nosniff"


async def commit_publication(case, token, receipts, manifest):
    async with case.factory() as session:
        result = await publish_release_artifacts(
            session, **case.scope, token=token, receipts=receipts, manifest_json=manifest
        )
        await session.commit()
        return result


@pytest.mark.anyio
async def test_rolled_back_publication_exposes_no_partial_artifacts_and_replay_is_idempotent(
    publication_env,
):
    case, token = publication_env, uuid4()
    receipts, manifest = await prepared(case, token)
    async with case.factory() as session:
        await publish_release_artifacts(
            session, **case.scope, token=token, receipts=receipts, manifest_json=manifest
        )
        await session.rollback()  # Worker interruption before commit.
    metadata = (await case.client.get(case.item, headers=case.headers)).json()
    assert metadata["job"]["status"] == "running" and metadata["artifacts"] == []
    assert (
        await case.client.get(case.item + "/artifacts/web", headers=case.headers)
    ).status_code == 404
    assert case.store.calls == []
    first = await commit_publication(case, token, receipts, manifest)
    replay = await commit_publication(case, token, receipts, manifest)
    assert not replay.changed and replay.artifact_ids == first.artifact_ids
    events = (
        await case.client.get(
            f"{case.item}/jobs/{case.scope['job_id']}/events", headers=case.headers
        )
    ).json()
    assert [row["code"] for row in events].count("release.completed") == 1


@pytest.mark.anyio
async def test_superseded_fence_cannot_publish_or_overwrite_recovery_artifacts(publication_env):
    case, first, recovery = publication_env, uuid4(), uuid4()
    old_receipts, old_manifest = await prepared(case, first)
    async with case.factory() as session:
        assert (await claim_release_execution(session, **case.scope, token=recovery)).acquired
        await session.commit()
    stale = await commit_publication(case, first, old_receipts, old_manifest)
    assert stale.status == "stale" and not stale.changed
    assert (
        await case.client.get(case.item + "/artifacts/web", headers=case.headers)
    ).status_code == 404
    receipts, manifest = await prepared(case, recovery, claim=False)
    winner = await commit_publication(case, recovery, receipts, manifest)
    late = await commit_publication(case, first, old_receipts, old_manifest)
    assert (
        late.status == "completed" and not late.changed and late.artifact_ids == winner.artifact_ids
    )


@pytest.mark.anyio
async def test_cancel_committed_before_publication_wins_even_with_uploaded_objects(publication_env):
    case, token = publication_env, uuid4()
    receipts, manifest = await prepared(case, token)
    cancelled = await case.client.post(
        f"{case.item}/jobs/{case.scope['job_id']}/cancel", headers=case.headers
    )
    assert cancelled.json()["cancel_requested"]
    result = await commit_publication(case, token, receipts, manifest)
    assert result.status == "cancelled" and result.changed and result.artifact_ids == ()
    metadata = (await case.client.get(case.item, headers=case.headers)).json()
    assert metadata["job"]["status"] == "cancelled" and metadata["artifacts"] == []
    assert (
        await case.client.get(case.item + "/artifacts/source", headers=case.headers)
    ).status_code == 404
    assert len(case.store.objects) == 3 and case.store.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("invalid", ["missing", "foreign_key", "manifest", "total_cap"])
async def test_publication_rejects_incomplete_or_mismatched_receipts_before_any_visibility(
    publication_env, invalid
):
    case, token = publication_env, uuid4()
    receipts, manifest = await prepared(case, token)
    if invalid == "missing":
        receipts.pop("web")
    elif invalid == "foreign_key":
        receipts["source"] = replace(receipts["source"], key="tenants/foreign/source.zip")
    elif invalid == "manifest":
        manifest += b" "
        receipts["manifest"] = replace(
            receipts["manifest"],
            sha256=hashlib.sha256(manifest).hexdigest(),
            size_bytes=len(manifest),
        )
    else:
        for kind in ("source", "web"):
            receipts[kind] = replace(receipts[kind], size_bytes=67108864)
        async with case.factory() as session:
            release = await session.get(NarrativeRelease, case.scope["release_id"])
            manifest = make_release_manifest(
                release, job_id=case.scope["job_id"], source=receipts["source"], web=receipts["web"]
            )
        receipts["manifest"] = replace(
            receipts["manifest"],
            size_bytes=len(manifest),
            sha256=hashlib.sha256(manifest).hexdigest(),
        )
    async with case.factory() as session:
        with pytest.raises(ValueError, match=r"^Invalid release artifact metadata$"):
            await publish_release_artifacts(
                session, **case.scope, token=token, receipts=receipts, manifest_json=manifest
            )
        await session.rollback()
    metadata = (await case.client.get(case.item, headers=case.headers)).json()
    assert metadata["job"]["status"] == "running" and metadata["artifacts"] == []
    assert case.store.calls == []


@pytest.mark.anyio
async def test_signed_viewer_foreign_scope_revocation_archive_and_store_failure(publication_env):
    case, token = publication_env, uuid4()
    receipts, manifest = await prepared(case, token)
    await commit_publication(case, token, receipts, manifest)
    member = await case.client.post(
        f"/v1/workspaces/{case.scope['tenant_id']}/members",
        headers=case.headers,
        json={"oidc_subject": "artifact-viewer", "role": "viewer"},
    )
    assert member.status_code == 201
    viewer = {
        "Authorization": "Bearer " + case.auth("artifact-viewer"),
        "X-Tenant-ID": str(case.scope["tenant_id"]),
    }
    url = case.item + "/artifacts/source"
    assert (await case.client.get(url, headers=viewer)).status_code == 200
    calls = len(case.store.calls)
    other = (
        await case.client.post(
            "/v1/workspaces", headers=case.headers, json={"name": "Foreign published games"}
        )
    ).json()
    assert (
        await case.client.get(url, headers={**case.headers, "X-Tenant-ID": other["id"]})
    ).status_code == 404
    assert (
        await case.client.get(url, headers={"X-Tenant-ID": str(case.scope["tenant_id"])})
    ).status_code == 401
    async with case.factory() as session:
        await session.execute(
            update(WorkspaceMembership)
            .where(
                WorkspaceMembership.tenant_id == case.scope["tenant_id"],
                WorkspaceMembership.user_id == UUID(member.json()["user_id"]),
            )
            .values(status=WorkspaceMembershipStatus.DISABLED)
        )
        await session.commit()
    assert (await case.client.get(url, headers=viewer)).status_code == 403
    assert len(case.store.calls) == calls
    project = f"/v1/narrative/projects/{case.project['id']}"
    assert (
        await case.client.post(
            project + "/archive",
            headers=case.headers,
            json={"archived": True, "base_revision_id": case.project["head_revision_id"]},
        )
    ).status_code == 200
    assert (await case.client.get(url, headers=case.headers)).status_code == 404
    assert (
        await case.client.get(url + "?include_archived=true", headers=case.headers)
    ).status_code == 200
    case.store.fail = True
    unavailable = await case.client.get(url + "?include_archived=true", headers=case.headers)
    assert unavailable.status_code == 503 and "owned source fixture" not in unavailable.text


@pytest.mark.anyio
async def test_postgres_publish_and_cancel_serialize_without_partial_success(publication_env):
    case, token = publication_env, uuid4()
    if case.backend != "postgres":
        pytest.skip("Requires actual PostgreSQL release/job locks")
    receipts, manifest = await prepared(case, token)
    async with case.factory() as blocker:
        await blocker.scalar(
            select(NarrativeRelease)
            .where(NarrativeRelease.id == case.scope["release_id"])
            .with_for_update()
        )
        pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
        tasks = [
            asyncio.create_task(commit_publication(case, token, receipts, manifest)),
            asyncio.create_task(
                case.client.post(
                    f"{case.item}/jobs/{case.scope['job_id']}/cancel", headers=case.headers
                )
            ),
        ]
        try:
            async with asyncio.timeout(5):
                while True:
                    async with case.factory() as observer:
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
                            {"blocker": pid},
                        )
                    if waiting == 2:
                        break
                    await asyncio.sleep(0.02)
        finally:
            await blocker.rollback()
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
    metadata = (await case.client.get(case.item, headers=case.headers)).json()
    assert metadata["job"]["status"] in ("completed", "cancelled")
    assert len(metadata["artifacts"]) == (3 if metadata["job"]["status"] == "completed" else 0)
    response = await case.client.get(case.item + "/artifacts/source", headers=case.headers)
    assert response.status_code == (200 if metadata["job"]["status"] == "completed" else 404)
