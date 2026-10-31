"""Asset folders: editor-only organization of the project library (ADR 0043)."""

from uuid import uuid4

import pytest
from test_narrative_asset_library_api import FONT, rgba_png, upload
from test_narrative_characters_api import (  # noqa: F401 - shared fixture and fakes
    queue_job,
    run_job,
    studio,
)


async def sprite(client, headers, base, name, width=12):
    response = await upload(
        client,
        headers,
        base,
        kind="sprite",
        name=name,
        data=rgba_png(width=width),
        filename=f"{name}.png",
        media="image/png",
    )
    assert response.status_code == 201, response.text
    return response.json()


async def folder(client, headers, base, name, parent=None, status=201):
    response = await client.post(
        f"{base}/asset-folders", headers=headers, json={"name": name, "parent_id": parent}
    )
    assert response.status_code == status, response.text
    return response.json()


async def index(client, headers, base):
    response = await client.get(f"{base}/asset-folders", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def listed(client, headers, base, **query):
    response = await client.get(f"{base}/assets", headers=headers, params=query)
    assert response.status_code == 200, response.text
    return [item["name"] for item in response.json()["assets"]]


@pytest.mark.anyio
async def test_folders_nest_rename_and_keep_sibling_names_unique(studio):  # noqa: F811
    client, _, _, headers, base, *_ = studio
    chapter = await folder(client, headers, base, "  Chapter 1  ")
    assert (chapter["name"], chapter["parent_id"]) == ("Chapter 1", None)
    harbor = await folder(client, headers, base, "Harbor", chapter["id"])
    night = await folder(client, headers, base, "Night", harbor["id"])
    # Three levels at most; sibling names are unique ignoring case; names are required.
    await folder(client, headers, base, "Too deep", night["id"], status=422)
    await folder(client, headers, base, "chapter 1", status=409)
    await folder(client, headers, base, "Harbor")  # The same name at another level is fine.
    await folder(client, headers, base, "   ", status=422)
    await folder(client, headers, base, "x" * 81, status=422)
    await folder(client, headers, base, "Lost", str(uuid4()), status=404)

    renamed = await client.patch(
        f"{base}/asset-folders/{harbor['id']}", headers=headers, json={"name": "Docks"}
    )
    assert renamed.status_code == 200 and renamed.json()["name"] == "Docks"
    # A folder cannot move into itself or its own descendant, nor past the depth limit.
    for parent in (harbor["id"], night["id"]):
        cycle = await client.patch(
            f"{base}/asset-folders/{harbor['id']}", headers=headers, json={"parent_id": parent}
        )
        assert cycle.status_code == 422, cycle.text
    other = await folder(client, headers, base, "Other")
    inner = await folder(client, headers, base, "Inner", other["id"])
    deep = await client.patch(
        f"{base}/asset-folders/{chapter['id']}", headers=headers, json={"parent_id": inner["id"]}
    )
    assert deep.status_code == 422
    moved = await client.patch(
        f"{base}/asset-folders/{night['id']}", headers=headers, json={"parent_id": None}
    )
    assert moved.status_code == 200 and moved.json()["parent_id"] is None
    names = sorted(
        (item["name"], item["parent_id"])
        for item in (await index(client, headers, base))["folders"]
    )
    assert ("Docks", chapter["id"]) in names and ("Night", None) in names


@pytest.mark.anyio
async def test_moving_assets_files_them_without_changing_bytes_and_counts_groups(studio):  # noqa: F811
    client, factory, store, headers, base, *_ = studio
    one = await sprite(client, headers, base, "Mira neutral", width=12)
    two = await sprite(client, headers, base, "Mira happy", width=14)
    font = await upload(
        client,
        headers,
        base,
        kind="font",
        name="Plain",
        data=FONT,
        filename="Plain.ttf",
        media="font/ttf",
    )
    assert font.status_code == 201
    _, payload = await queue_job(client, headers, base, character="mira")
    assert (await run_job(factory, store, payload))["status"] == "completed"

    cast = await folder(client, headers, base, "Cast")
    mira = await folder(client, headers, base, "Mira", cast["id"])
    response = await client.post(
        f"{base}/assets/move",
        headers=headers,
        json={"asset_ids": [one["id"], two["id"]], "folder_id": mira["id"]},
    )
    assert response.status_code == 200, response.text
    assert {item["folder_id"] for item in response.json()["assets"]} == {mira["id"]}
    assert all(
        item["sha256"] in (one["sha256"], two["sha256"]) for item in response.json()["assets"]
    )
    assert await listed(client, headers, base, folder=mira["id"]) == ["Mira happy", "Mira neutral"]
    assert await listed(client, headers, base, folder=cast["id"]) == []
    unfiled = await listed(client, headers, base, folder="none")
    assert "Plain" in unfiled and "Mira happy" not in unfiled
    assert await listed(client, headers, base, character_id="mira") == [
        "mira portrait 1",
        "mira portrait 2",
    ]
    content = await client.get(f"{base}/assets/{one['id']}/content", headers=headers)
    assert content.content == rgba_png(width=12)

    summary = await index(client, headers, base)
    counts = {item["id"]: item["asset_count"] for item in summary["folders"]}
    assert counts == {cast["id"]: 0, mira["id"]: 2}
    assert summary["unfiled"] == 3 and summary["to_review"] == 2 and summary["total"] == 5
    assert summary["kinds"] == {"character_portrait": 2, "font": 1, "sprite": 2}
    assert summary["characters"] == {"mira": 2}

    # Deleting a folder hands its folders and assets to its parent.
    deleted = await client.delete(f"{base}/asset-folders/{cast['id']}", headers=headers)
    assert deleted.status_code == 204
    after = await index(client, headers, base)
    assert [(item["name"], item["parent_id"]) for item in after["folders"]] == [("Mira", None)]
    assert await listed(client, headers, base, folder=mira["id"]) == ["Mira happy", "Mira neutral"]
    await client.delete(f"{base}/asset-folders/{mira['id']}", headers=headers)
    assert (await index(client, headers, base))["unfiled"] == 5

    back = await client.post(
        f"{base}/assets/move", headers=headers, json={"asset_ids": [one["id"]], "folder_id": None}
    )
    assert back.status_code == 200
    for bad in (
        {"asset_ids": [], "folder_id": None},
        {"asset_ids": [one["id"]] * 101, "folder_id": None},
        {"asset_ids": [one["id"]], "folder_id": str(uuid4())},
        {"asset_ids": [str(uuid4())], "folder_id": None},
    ):
        refused = await client.post(f"{base}/assets/move", headers=headers, json=bad)
        assert refused.status_code in (404, 422), refused.text


@pytest.mark.anyio
async def test_folders_are_project_scoped_and_need_a_member(studio):  # noqa: F811
    client, _, _, headers, base, workspace, oidc_auth = studio
    mine = await folder(client, headers, base, "Mine")
    asset = await sprite(client, headers, base, "Kept")
    other = (
        await client.post(
            "/v1/narrative/projects",
            headers=headers,
            json={"name": "Other", "idempotency_key": str(uuid4())},
        )
    ).json()
    elsewhere = f"/v1/narrative/projects/{other['id']}"
    assert (await index(client, headers, elsewhere))["folders"] == []
    foreign = await client.post(
        f"{elsewhere}/assets/move",
        headers=headers,
        json={"asset_ids": [asset["id"]], "folder_id": None},
    )
    assert foreign.status_code == 404
    into_foreign = await client.post(
        f"{base}/assets/move",
        headers=headers,
        json={
            "asset_ids": [asset["id"]],
            "folder_id": (await folder(client, headers, elsewhere, "X"))["id"],
        },
    )
    assert into_foreign.status_code == 404
    assert (
        await client.delete(f"{elsewhere}/asset-folders/{mine['id']}", headers=headers)
    ).status_code == 404

    added = await client.post(
        f"/v1/workspaces/{workspace['id']}/members",
        headers=headers,
        json={
            "oidc_issuer": "https://keycloak.example/realms/flintgraph",
            "oidc_subject": "folder-viewer",
            "role": "viewer",
        },
    )
    assert added.status_code == 201
    viewer = {**headers, "Authorization": "Bearer " + oidc_auth("folder-viewer")}
    assert (await client.get(f"{base}/asset-folders", headers=viewer)).status_code == 200
    assert (
        await client.post(f"{base}/asset-folders", headers=viewer, json={"name": "No"})
    ).status_code == 403
    assert (
        await client.post(
            f"{base}/assets/move",
            headers=viewer,
            json={"asset_ids": [asset["id"]], "folder_id": None},
        )
    ).status_code == 403

    head = (await client.get(base, headers=headers)).json()["head_revision_id"]
    archived = await client.post(
        f"{base}/archive", headers=headers, json={"base_revision_id": head, "archived": True}
    )
    assert archived.status_code == 200, archived.text
    refused = await client.post(f"{base}/asset-folders", headers=headers, json={"name": "Late"})
    assert refused.status_code == 409
