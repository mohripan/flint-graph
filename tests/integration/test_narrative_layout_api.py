"""Editor-only scene hierarchy: shared, versioned, nested, never part of story content."""

from uuid import uuid4

import pytest

from flint_graph.config import Settings, get_settings
from flint_graph.main import app


@pytest.fixture
def layout_settings(narrative_env):
    app.dependency_overrides[get_settings] = lambda: Settings(env="test")
    yield
    app.dependency_overrides.pop(get_settings, None)


async def new_story(client, name="Layout fixture", auth=None):
    workspace = (await client.post("/v1/workspaces", headers=auth, json={"name": name})).json()
    headers = {**(auth or {}), "X-Tenant-ID": workspace["id"]}
    project = (
        await client.post(
            "/v1/narrative/projects",
            headers=headers,
            json={"name": name, "idempotency_key": str(uuid4())},
        )
    ).json()
    return headers, project, f"/v1/narrative/projects/{project['id']}/layout"


def group(group_id, name, *items, collapsed=False):
    return {
        "type": "group",
        "id": group_id,
        "name": name,
        "collapsed": collapsed,
        "items": list(items),
    }


def scene(scene_id):
    return {"type": "scene", "id": scene_id}


LAYOUT = {
    "items": [
        group(
            "route_mira",
            "Mira's route",
            group("chapter_one", "Chapter 1", scene("opening"), scene("storm")),
            group("chapter_two", "Chapter 2", scene("tower"), collapsed=True),
        ),
        group("endings", "Endings", scene("ending")),
        scene("notes_scene"),
    ]
}


@pytest.mark.anyio
async def test_layout_starts_empty_and_saves_with_an_optimistic_version(
    narrative_env, layout_settings
):
    client, _, _ = narrative_env
    headers, project, path = await new_story(client)
    empty = (await client.get(path, headers=headers)).json()
    assert empty == {"project_id": project["id"], "version": 0, "items": []}
    saved = await client.put(path, headers=headers, json={"base_version": 0, **LAYOUT})
    assert saved.status_code == 200
    assert saved.json() == {"project_id": project["id"], "version": 1, **LAYOUT}
    assert (await client.get(path, headers=headers)).json() == saved.json()
    moved = {"items": LAYOUT["items"][::-1]}
    second = await client.put(path, headers=headers, json={"base_version": 1, **moved})
    assert second.json()["version"] == 2 and second.json()["items"][0] == scene("notes_scene")
    stale = await client.put(path, headers=headers, json={"base_version": 1, **LAYOUT})
    assert stale.status_code == 409
    assert stale.json()["type"].endswith("stale-layout")
    current = (await client.get(path, headers=headers)).json()
    assert current["version"] == 2 and current["items"][0] == scene("notes_scene")
    revision = (
        await client.get(
            f"/v1/narrative/projects/{project['id']}/revisions/{project['head_revision_id']}",
            headers=headers,
        )
    ).json()
    assert "chapter_one" not in revision["story_json"], "Layout never changes story content"


def nested(depth):
    item = scene("deep")
    for level in range(depth):
        item = group(f"level_{level}", "Level", item)
    return {"items": [item]}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "layout",
    [
        {"items": [scene("opening"), scene("opening")]},
        {"items": [group("a", "A", scene("opening")), scene("opening")]},
        {"items": [group("a", "A"), group("a", "B")]},
        {"items": [group("Bad Id", "A")]},
        {"items": [group("a", "")]},
        {"items": [group("a", "x" * 81)]},
        {"items": [scene("Not An Id")]},
        {"items": [group(f"g{i}", "G") for i in range(501)]},
        nested(5),
        {"items": [], "extra": True},
        {"items": [{"type": "folder", "id": "a"}]},
    ],
)
async def test_invalid_layouts_are_rejected(narrative_env, layout_settings, layout):
    client, _, _ = narrative_env
    headers, _, path = await new_story(client)
    response = await client.put(path, headers=headers, json={"base_version": 0, **layout})
    assert response.status_code == 422
    assert (await client.get(path, headers=headers)).json()["version"] == 0


@pytest.mark.anyio
async def test_four_levels_and_a_long_story_fit(narrative_env, layout_settings):
    client, _, _ = narrative_env
    headers, _, path = await new_story(client)
    chapters = [
        group(f"chapter_{c}", f"Chapter {c}", *[scene(f"s{c}_{n}") for n in range(400)])
        for c in range(25)
    ]
    long_story = {"items": [group("route", "Route", *chapters), *nested(4)["items"]]}
    saved = await client.put(path, headers=headers, json={"base_version": 0, **long_story})
    assert saved.status_code == 200 and saved.json()["version"] == 1


@pytest.mark.anyio
async def test_viewers_read_members_write_and_foreign_or_archived_projects_are_refused(
    narrative_env, oidc_auth
):
    client, _, _ = narrative_env
    owner = {"Authorization": "Bearer " + oidc_auth("layout-owner")}
    headers, project, path = await new_story(client, auth=owner)
    assert (
        await client.post(
            f"/v1/workspaces/{project['tenant_id']}/members",
            headers=owner,
            json={
                "oidc_issuer": "https://keycloak.example/realms/flintgraph",
                "oidc_subject": "layout-viewer",
                "role": "viewer",
            },
        )
    ).status_code == 201
    viewer = {**headers, "Authorization": "Bearer " + oidc_auth("layout-viewer")}
    saved = await client.put(path, headers=headers, json={"base_version": 0, **LAYOUT})
    assert saved.status_code == 200
    assert (await client.get(path, headers=viewer)).json()["version"] == 1
    assert (
        await client.put(path, headers=viewer, json={"base_version": 1, **LAYOUT})
    ).status_code == 403
    foreign_headers, _, foreign_path = await new_story(client, name="Foreign", auth=owner)
    assert (await client.get(foreign_path, headers=headers)).status_code == 404
    assert (await client.get(path, headers=foreign_headers)).status_code == 404
    archived = await client.post(
        f"/v1/narrative/projects/{project['id']}/archive",
        headers=headers,
        json={"base_revision_id": project["head_revision_id"], "archived": True},
    )
    assert archived.status_code == 200
    refused = await client.put(path, headers=headers, json={"base_version": 1, **LAYOUT})
    assert refused.status_code == 409
