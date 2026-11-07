"""Moving a project to the trash, restoring it, and deleting it forever (ADR 0073)."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_narrative_asset_library_api import MUSIC, rgba_png, upload
from test_narrative_assistant_api import (
    ask,
    assistant_settings,  # noqa: F401 - a fixture this file's tests ask for by name.
    new_thread,
    proposal,
    turns,
    work,
)
from test_narrative_characters_api import (
    studio,  # noqa: F401 - a shared fixture.
)
from test_narrative_releases_api import (
    release_configuration,  # noqa: F401 - a shared fixture.
)

from flint_graph.api.dependencies import get_narrative_artifact_store
from flint_graph.application.services.narrative_project_purge import project_tables
from flint_graph.infrastructure.narrative_artifact_store import ArtifactStoreError
from flint_graph.main import app


class FilesStore:
    """Holds keys the way the bucket does, so deleting can be checked against what is left."""

    def __init__(self):
        self.keys = set()
        self.fail = False

    async def delete_project_files(self, *, tenant_id, project_id, release_ids):
        if self.fail:
            raise ArtifactStoreError("artifact_unavailable")
        prefixes = [
            f"tenants/{tenant_id}/narrative/projects/{project_id}/",
            *(f"tenants/{tenant_id}/narrative/releases/{item}/" for item in release_ids),
        ]
        self.keys = {key for key in self.keys if not key.startswith(tuple(prefixes))}


@pytest.fixture
def files():
    store = FilesStore()
    app.dependency_overrides[get_narrative_artifact_store] = lambda: store
    yield store
    app.dependency_overrides.pop(get_narrative_artifact_store, None)


async def new_story(client, name="Trash fixture"):
    workspace = (await client.post("/v1/workspaces", json={"name": name + uuid4().hex})).json()
    headers = {"X-Tenant-ID": workspace["id"]}
    project = (
        await client.post(
            "/v1/narrative/projects",
            headers=headers,
            json={"name": name, "idempotency_key": str(uuid4())},
        )
    ).json()
    return headers, project, f"/v1/narrative/projects/{project['id']}"


async def trash(client, headers, project, path, *, archived=True):
    return await client.post(
        f"{path}/archive",
        headers=headers,
        json={"base_revision_id": project["head_revision_id"], "archived": archived},
    )


async def names(client, headers, **query):
    response = await client.get("/v1/narrative/projects", headers=headers, params=query)
    return [item["name"] for item in response.json()]


async def rows_left(factory, project_id):
    """How many rows each project table still holds for this project."""
    async with factory() as session:
        left = {}
        for table in project_tables():
            count = await session.scalar(
                select(func.count()).select_from(table).where(table.c.project_id == project_id)
            )
            if count:
                left[table.name] = count
        return left


@pytest.mark.anyio
async def test_the_trash_hides_a_project_and_restoring_brings_it_all_back(narrative_env, files):
    client, _, _ = narrative_env
    headers, project, path = await new_story(client, "Ferry")
    assert (await trash(client, headers, project, path)).status_code == 200
    assert await names(client, headers) == []
    assert await names(client, headers, trashed="true") == ["Ferry"]
    assert (await client.get(path, headers=headers)).status_code == 404

    restored = await trash(client, headers, project, path, archived=False)
    assert restored.status_code == 200
    assert await names(client, headers) == ["Ferry"]
    assert await names(client, headers, trashed="true") == []
    assert (await client.get(path, headers=headers)).status_code == 200


@pytest.mark.anyio
async def test_a_project_must_be_in_the_trash_before_it_can_be_deleted(narrative_env, files):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    refused = await client.delete(path, headers=headers)
    assert refused.status_code == 409
    assert "trash" in refused.json()["detail"]
    assert (await client.get(path, headers=headers)).status_code == 200
    assert await rows_left(factory, UUID(project["id"]))


@pytest.mark.anyio
async def test_the_warning_counts_what_would_be_lost(narrative_env, files):
    client, _, _ = narrative_env
    headers, project, path = await new_story(client)
    await trash(client, headers, project, path)
    contents = (await client.get(f"{path}/contents", headers=headers)).json()
    assert contents == {
        "revisions": 1,
        "files": 0,
        "characters": 0,
        "conversations": 0,
        "releases": 0,
        "working": [],
    }


@pytest.mark.anyio
@pytest.mark.usefixtures("assistant_settings")
async def test_deleting_forever_leaves_no_row_and_no_file_of_that_project(narrative_env, files):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    other_headers, other, _ = await new_story(client, "Another story")
    tenant = headers["X-Tenant-ID"]
    thread = await new_thread(client, headers, path)
    turn = (await ask(client, headers, path, thread, project["head_revision_id"])).json()
    await work(factory, turn["id"], proposal())
    # A second revision, which points at the first; the immutable table must let both go.
    made = (await turns(client, headers, path, thread))[0]["proposal"]["id"]
    accepted = await client.post(
        f"{path}/assistant/proposals/{made}/accept",
        headers=headers,
        json={"idempotency_key": str(uuid4())},
    )
    assert accepted.status_code == 201, accepted.text
    project = (await client.get(path, headers=headers)).json()
    keep = f"tenants/{other['tenant_id']}/narrative/projects/{other['id']}/assets/a/image.png"
    gone = f"tenants/{tenant}/narrative/projects/{project['id']}/assets/a/image.png"
    files.keys = {keep, gone}
    await trash(client, headers, project, path)
    assert (await rows_left(factory, UUID(project["id"])))["narrative_assistant_turns"] == 1

    deleted = await client.delete(path, headers=headers)
    assert deleted.status_code == 204
    assert await rows_left(factory, UUID(project["id"])) == {}
    assert files.keys == {keep}, "another project's files stay"
    assert await rows_left(factory, UUID(other["id"])), "another project's rows stay"
    assert (await client.get(path + "?include_archived=true", headers=headers)).status_code == 404
    assert await names(client, headers, trashed="true") == []
    assert (await client.delete(path, headers=headers)).status_code == 404
    assert (
        await client.get(f"/v1/narrative/projects/{other['id']}", headers=other_headers)
    ).status_code == 200


@pytest.mark.anyio
async def test_a_project_full_of_files_and_folders_is_emptied(studio):  # noqa: F811
    client, factory, store, headers, base, *_ = studio
    project_id = UUID(base.rsplit("/", 1)[1])
    folder = await client.post(
        f"{base}/asset-folders", headers=headers, json={"name": "Harbor", "parent_id": None}
    )
    inner = await client.post(
        f"{base}/asset-folders",
        headers=headers,
        json={"name": "Night", "parent_id": folder.json()["id"]},
    )
    assert inner.status_code == 201, inner.text
    picture = await upload(
        client,
        headers,
        base,
        kind="sprite",
        name="Mira",
        data=rgba_png(),
        filename="mira.png",
        media="image/png",
    )
    song = await upload(
        client,
        headers,
        base,
        kind="music",
        name="Theme",
        data=MUSIC,
        filename="theme.ogg",
        media="audio/ogg",
    )
    assert picture.status_code == song.status_code == 201
    moved = await client.post(
        f"{base}/assets/move",
        headers=headers,
        json={"asset_ids": [picture.json()["id"]], "folder_id": inner.json()["id"]},
    )
    assert moved.status_code == 200, moved.text
    assert store.objects, "the uploads reached the store"

    project = (await client.get(base, headers=headers)).json()
    await trash(client, headers, project, base)
    contents = (await client.get(f"{base}/contents", headers=headers)).json()
    assert contents["files"] == 2

    assert (await client.delete(base, headers=headers)).status_code == 204
    assert store.objects == {}
    assert await rows_left(factory, project_id) == {}


@pytest.mark.anyio
@pytest.mark.usefixtures("release_configuration")
async def test_a_released_game_goes_with_its_project(narrative_env, files):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    request = {"revision_id": project["head_revision_id"], "idempotency_key": str(uuid4())}
    release = (await client.post(f"{path}/releases", headers=headers, json=request)).json()
    item = f"{path}/releases/{release['id']}"
    await trash(client, headers, project, path)

    contents = (await client.get(f"{path}/contents", headers=headers)).json()
    assert (contents["releases"], contents["working"]) == (1, ["1 release build"])
    assert (await client.delete(path, headers=headers)).status_code == 409

    cancelled = await client.post(f"{item}/jobs/{release['job']['id']}/cancel", headers=headers)
    assert cancelled.status_code == 200, cancelled.text
    tenant = headers["X-Tenant-ID"]
    built = f"tenants/{tenant}/narrative/releases/{release['id']}/jobs/j/executions/e/web.zip"
    files.keys = {built}
    assert (await client.delete(path, headers=headers)).status_code == 204
    assert files.keys == set()
    assert await rows_left(factory, UUID(project["id"])) == {}


@pytest.mark.anyio
@pytest.mark.usefixtures("assistant_settings")
async def test_nothing_is_deleted_while_the_project_is_still_working(narrative_env, files):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    thread = await new_thread(client, headers, path)
    created = await ask(client, headers, path, thread, project["head_revision_id"])
    assert created.status_code == 202
    await trash(client, headers, project, path)
    contents = (await client.get(f"{path}/contents", headers=headers)).json()
    assert contents["working"] == ["1 assistant reply"]

    files.keys = {f"tenants/{headers['X-Tenant-ID']}/narrative/projects/{project['id']}/x"}
    refused = await client.delete(path, headers=headers)
    assert refused.status_code == 409
    assert "1 assistant reply" in refused.json()["detail"]
    assert files.keys, "no file was touched"
    assert await rows_left(factory, UUID(project["id"]))
    # Refused before it began, so restoring still works.
    assert (await trash(client, headers, project, path, archived=False)).status_code == 200


@pytest.mark.anyio
async def test_a_failure_midway_keeps_it_in_the_trash_and_trying_again_finishes(
    narrative_env, files
):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    await trash(client, headers, project, path)
    files.fail = True
    failed = await client.delete(path, headers=headers)
    assert failed.status_code == 503
    assert "try again" in failed.json()["detail"].lower()
    assert "tenants/" not in failed.text

    listed = await client.get("/v1/narrative/projects?trashed=true", headers=headers)
    assert listed.json()[0]["purge_started_at"] is not None
    # Some files may already be gone, so it can no longer come back whole.
    refused = await trash(client, headers, project, path, archived=False)
    assert refused.status_code == 409

    files.fail = False
    assert (await client.delete(path, headers=headers)).status_code == 204
    assert await rows_left(factory, UUID(project["id"])) == {}


@pytest.mark.anyio
async def test_only_an_admin_of_that_workspace_can_delete(narrative_env, files, oidc_auth):
    client, factory, _ = narrative_env

    def user(subject):
        return {"Authorization": "Bearer " + oidc_auth(subject)}

    owner = user("trash-owner")
    workspace = (
        await client.post("/v1/workspaces", headers=owner, json={"name": "Trash roles"})
    ).json()
    headers = {**owner, "X-Tenant-ID": workspace["id"]}
    project = (
        await client.post(
            "/v1/narrative/projects",
            headers=headers,
            json={"name": "Roles", "idempotency_key": str(uuid4())},
        )
    ).json()
    path = f"/v1/narrative/projects/{project['id']}"
    added = await client.post(
        f"/v1/workspaces/{workspace['id']}/members",
        headers=owner,
        json={
            "oidc_issuer": "https://keycloak.example/realms/flintgraph",
            "oidc_subject": "trash-member",
            "role": "member",
        },
    )
    assert added.status_code == 201
    member = {**user("trash-member"), "X-Tenant-ID": workspace["id"]}
    elsewhere = (
        await client.post("/v1/workspaces", headers=user("trash-stranger"), json={"name": "Away"})
    ).json()
    stranger = {**user("trash-stranger"), "X-Tenant-ID": elsewhere["id"]}

    await trash(client, headers, project, path)
    assert (await client.delete(path, headers=member)).status_code == 403
    assert (await client.get(f"{path}/contents", headers=member)).status_code == 403
    assert (await client.delete(path, headers=stranger)).status_code == 404
    assert await rows_left(factory, UUID(project["id"]))
    assert (await client.delete(path, headers=headers)).status_code == 204


@pytest.mark.anyio
async def test_renaming_changes_the_name_and_nothing_else(narrative_env, files):
    client, _, _ = narrative_env
    headers, project, path = await new_story(client, "Testing assistant")
    renamed = await client.post(f"{path}/rename", headers=headers, json={"name": "  The Ferry  "})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "The Ferry"
    assert renamed.json()["head_revision_id"] == project["head_revision_id"]
    assert await names(client, headers) == ["The Ferry"]
    for bad in ("", "   ", "x" * 201):
        refused = await client.post(f"{path}/rename", headers=headers, json={"name": bad})
        assert refused.status_code == 422, bad

    await trash(client, headers, renamed.json(), path)
    assert (
        await client.post(f"{path}/rename", headers=headers, json={"name": "No"})
    ).status_code == 409


@pytest.mark.anyio
@pytest.mark.usefixtures("assistant_settings")
async def test_the_logs_still_refuse_changes_unless_their_own_project_is_being_deleted(
    narrative_env, files, request
):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    _, other, other_path = await new_story(client, "Being deleted")
    other_headers = {"X-Tenant-ID": other["tenant_id"]}
    thread = await new_thread(client, headers, path)
    turn = (await ask(client, headers, path, thread, project["head_revision_id"])).json()
    await work(factory, turn["id"], proposal())
    await trash(client, other_headers, other, other_path)
    files.fail = True
    assert (await client.delete(other_path, headers=other_headers)).status_code == 503
    await trash(client, headers, project, path)

    mine = {"project": UUID(project["id"]).hex}
    if "postgres" in request.node.name:
        mine = {"project": UUID(project["id"])}
    delete_log = text("DELETE FROM narrative_assistant_thread_events WHERE project_id = :project")
    async with factory() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(delete_log, mine)
    if "postgres" in request.node.name:
        # Revisions and releases have their triggers only in PostgreSQL.
        delete_revisions = text("DELETE FROM narrative_revisions WHERE project_id = :project")
        async with factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(delete_revisions, mine)
    assert await rows_left(factory, UUID(project["id"]))

    # Once its own delete has begun, the log can go, but it still cannot be rewritten.
    assert (await client.delete(path, headers=headers)).status_code == 503
    rewrite_log = text(
        "UPDATE narrative_assistant_thread_events SET kind = 'x' WHERE project_id = :project"
    )
    async with factory() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(rewrite_log, mine)
