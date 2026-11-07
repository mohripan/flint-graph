"""Attaching a screenshot to a message: kept safely, and described for the assistant."""

import hashlib
from uuid import UUID, uuid4

import pytest
from test_narrative_asset_library_api import rgba_png
from test_narrative_assistant_api import claim, new_thread
from test_narrative_package_v2_api import configure, v2  # noqa: F401

from flint_graph.application.services.narrative_assistant_images import (
    MAX_IMAGE_BYTES,
    describe_attached,
    turn_images,
)
from flint_graph.infrastructure.db.models import NarrativeAssistantImage

pytestmark = pytest.mark.anyio


class Sees:
    def __init__(self, reply="A rainy street. No characters are visible."):
        self.reply, self.calls = reply, []

    async def describe(self, png, prompt):
        self.calls.append((png, prompt))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


async def picture(client, headers, base, data=None, name="shot.png", media="image/png"):
    return await client.post(
        f"{base}/assistant/images",
        headers=headers,
        files={"file": (name, rgba_png() if data is None else data, media)},
    )


async def ask_with(client, headers, base, thread, head, *image_ids):
    return await client.post(
        f"{base}/assistant/threads/{thread['id']}/turns",
        headers=headers,
        json={
            "request": "Why can't I see the character?",
            "base_revision_id": head,
            "idempotency_key": str(uuid4()),
            "attachments": [{"kind": "image", "id": item} for item in image_ids],
        },
    )


@pytest.fixture
def seeing(v2):  # noqa: F811
    configure(
        narrative_assistant_vision_model="vision-test", narrative_assistant_provider="deterministic"
    )
    return v2


async def head_of(client, headers, base):
    return (await client.get(base, headers=headers)).json()["head_revision_id"]


async def test_a_screenshot_is_kept_privately_and_read_back_exactly(seeing):
    client, _, store, owner, project = seeing
    base, _ = await project("Pictures", schema="2")
    created = await picture(client, owner, base)
    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["width"], body["height"]) == (12, 20)

    keys = [key for key in store.objects if "/assistant-images/" in key]
    assert len(keys) == 1
    assert f"/narrative/projects/{base.rsplit('/', 1)[1]}/" in keys[0], "goes with the project"
    read = await client.get(f"{base}/assistant/images/{body['id']}", headers=owner)
    assert read.status_code == 200
    assert read.headers["content-type"] == "image/png"
    assert read.headers["x-content-type-options"] == "nosniff"
    assert read.content == store.objects[keys[0]]


async def test_pasting_the_same_picture_twice_keeps_one_copy(seeing):
    client, _, store, owner, project = seeing
    base, _ = await project("Pictures", schema="2")
    first = (await picture(client, owner, base)).json()
    second = (await picture(client, owner, base)).json()
    assert first["id"] == second["id"]
    assert len([key for key in store.objects if "/assistant-images/" in key]) == 1


@pytest.mark.parametrize(
    ("data", "status"),
    [
        (b"not a picture at all", 422),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 40, 422),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * (MAX_IMAGE_BYTES + 1), 413),
    ],
    ids=["text", "broken", "huge"],
)
async def test_anything_but_a_real_png_is_refused(seeing, data, status):
    client, _, store, owner, project = seeing
    base, _ = await project("Pictures", schema="2")
    refused = await picture(client, owner, base, data=data)
    assert refused.status_code == status, refused.text
    assert not [key for key in store.objects if "/assistant-images/" in key]


async def test_without_a_vision_model_pictures_are_off_and_say_so(v2):  # noqa: F811
    client, _, _, owner, project = v2
    base, _ = await project("Pictures", schema="2")
    capabilities = await client.get(f"{base}/assistant/capabilities", headers=owner)
    assert capabilities.json()["images"] is False
    refused = await picture(client, owner, base)
    assert refused.status_code == 409
    assert "read pictures" in refused.json()["detail"]
    configure(narrative_assistant_vision_model="vision-test")
    assert (await client.get(f"{base}/assistant/capabilities", headers=owner)).json() == {
        "images": True,
        "max_images": 3,
    }


async def test_another_workspace_cannot_see_or_use_a_picture(seeing, oidc_auth):
    client, _, _, owner, project = seeing
    base, _ = await project("Pictures", schema="2")
    image = (await picture(client, owner, base)).json()

    stranger = {"Authorization": "Bearer " + oidc_auth("picture-stranger")}
    elsewhere = (
        await client.post("/v1/workspaces", headers=stranger, json={"name": "Away"})
    ).json()
    headers = {**stranger, "X-Tenant-ID": elsewhere["id"]}
    assert (
        await client.get(f"{base}/assistant/images/{image['id']}", headers=headers)
    ).status_code == 404
    assert (await picture(client, headers, base)).status_code == 404

    own = (
        await client.post(
            "/v1/narrative/projects",
            headers=headers,
            json={"name": "Mine", "idempotency_key": str(uuid4())},
        )
    ).json()
    mine = f"/v1/narrative/projects/{own['id']}"
    thread = await new_thread(client, headers, mine)
    refused = await ask_with(client, headers, mine, thread, own["head_revision_id"], image["id"])
    assert refused.status_code == 422


async def test_another_project_of_mine_cannot_use_it_either(seeing):
    client, _, _, owner, project = seeing
    base, _ = await project("One", schema="2")
    other, _ = await project("Two", schema="2")
    image = (await picture(client, owner, base)).json()
    thread = await new_thread(client, owner, other)
    head = await head_of(client, owner, other)
    assert (await ask_with(client, owner, other, thread, head, image["id"])).status_code == 422


async def test_a_message_carries_its_pictures_up_to_a_limit(seeing):
    client, _, _, owner, project = seeing
    base, _ = await project("Pictures", schema="2")
    images = [
        (await picture(client, owner, base, data=rgba_png(width=2 * (index + 2)))).json()["id"]
        for index in range(4)
    ]
    thread = await new_thread(client, owner, base)
    head = await head_of(client, owner, base)
    too_many = await ask_with(client, owner, base, thread, head, *images)
    assert too_many.status_code == 422
    assert "3 pictures" in too_many.json()["detail"]

    sent = await ask_with(client, owner, base, thread, head, *images[:2])
    assert sent.status_code == 202, sent.text
    assert [item["kind"] for item in sent.json()["attachments"]] == ["image", "image"]
    assert sent.json()["attachments"][0]["name"] == "Screenshot"


async def test_the_assistant_is_told_what_the_picture_shows_and_only_looks_once(seeing):
    client, factory, _, owner, project = seeing
    base, _ = await project("Pictures", schema="2")
    image = (await picture(client, owner, base)).json()
    thread = await new_thread(client, owner, base)
    head = await head_of(client, owner, base)
    turn = (await ask_with(client, owner, base, thread, head, image["id"])).json()

    work = await claim(factory, turn["id"], uuid4())
    assert [str(item.id) for item in work.images] == [image["id"]]
    vision = Sees()
    store = seeing[2]
    lines = await describe_attached(
        factory,
        store=store,
        vision=vision,
        tenant_id=work.tenant_id,
        project_id=work.project_id,
        images=work.images,
        request=work.request,
    )
    assert len(vision.calls) == 1
    assert hashlib.sha256(vision.calls[0][0]).hexdigest() == work.images[0].sha256
    assert "Why can't I see the character?" in vision.calls[0][1]
    assert len(lines) == 1
    assert "No characters are visible." in lines[0]
    assert "never add it to the story" in lines[0]

    async with factory() as session:
        saved = await session.get(NarrativeAssistantImage, work.images[0].id)
        assert saved.description == "A rainy street. No characters are visible."

    # A retry of the same turn, or the same picture sent again, does not look again.
    async with factory() as session:
        again = await turn_images(
            session,
            tenant_id=work.tenant_id,
            project_id=work.project_id,
            attachments=[{"kind": "image", "id": image["id"]}],
        )
    assert again[0].description == "A rainy street. No characters are visible."
    await describe_attached(
        factory,
        store=store,
        vision=vision,
        tenant_id=work.tenant_id,
        project_id=work.project_id,
        images=again,
        request=work.request,
    )
    assert len(vision.calls) == 1


async def test_a_picture_that_cannot_be_read_does_not_stop_the_reply(seeing):
    client, factory, _, owner, project = seeing
    base, _ = await project("Pictures", schema="2")
    image = (await picture(client, owner, base)).json()
    thread = await new_thread(client, owner, base)
    head = await head_of(client, owner, base)
    turn = (await ask_with(client, owner, base, thread, head, image["id"])).json()
    work = await claim(factory, turn["id"], uuid4())
    lines = await describe_attached(
        factory,
        store=seeing[2],
        vision=Sees(RuntimeError("the model fell over")),
        tenant_id=work.tenant_id,
        project_id=work.project_id,
        images=work.images,
        request=work.request,
    )
    assert "could not be read" in lines[0]
    assert "fell over" not in lines[0]
    # With no vision model at all, the same honest line.
    none = await describe_attached(
        factory,
        store=seeing[2],
        vision=None,
        tenant_id=work.tenant_id,
        project_id=work.project_id,
        images=work.images,
        request=work.request,
    )
    assert "could not be read" in none[0]


async def test_a_project_in_the_trash_takes_no_pictures_and_deleting_removes_them(seeing):
    client, factory, store, owner, project = seeing
    base, _ = await project("Pictures", schema="2")
    image = (await picture(client, owner, base)).json()
    saved = (await client.get(base, headers=owner)).json()
    trashed = await client.post(
        f"{base}/archive",
        headers=owner,
        json={"base_revision_id": saved["head_revision_id"], "archived": True},
    )
    assert trashed.status_code == 200
    assert (await picture(client, owner, base, data=rgba_png(width=8))).status_code == 409

    assert (await client.delete(base, headers=owner)).status_code == 204
    assert not [key for key in store.objects if "/assistant-images/" in key]
    async with factory() as session:
        assert await session.get(NarrativeAssistantImage, UUID(image["id"])) is None
