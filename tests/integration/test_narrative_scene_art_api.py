"""Event CGs drawn from an approved image of a character (ADR 0041 slice C); no GPU."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_narrative_characters_api import (
    ADAPTER,
    FakeGenerator,
    png,
    queue_job,
    run_job,
    studio,  # noqa: F401 - the shared fixture
)

from flint_graph.application.narrative_image_workflow import ImageJobPayload
from flint_graph.infrastructure.db.models import NarrativeImageJob

pytestmark = pytest.mark.anyio

QUEN = {
    "base_version": 0,
    "appearance": "shoulder-length white hair, red eyes, androgynous, casual clothes",
    "character_type": "boy",
    "framing": "full_body",
}


async def approved_portrait(client, factory, store, headers, base):
    """A generated portrait of Quen, approved the way the Characters tab does it."""
    job, payload = await queue_job(client, headers, base, character="quen", count=1)
    assert (await run_job(factory, store, payload))["status"] == "completed"
    [candidate] = (await client.get(f"{base}/image-jobs/{job['id']}", headers=headers)).json()[
        "assets"
    ]
    return candidate


def scene_body(reference_id, **changes):
    return {
        "scene": "Quen sitting on the couch by the window at night",
        "characters": [{"character_id": "quen", "reference_asset_id": reference_id}],
        "count": 2,
        "idempotency_key": str(uuid4()),
        **changes,
    }


async def test_scene_art_puts_an_approved_character_image_into_candidate_cgs(studio):  # noqa: F811
    client, factory, store, headers, base, *_ = studio
    saved = await client.put(f"{base}/characters/quen", headers=headers, json=QUEN)
    assert saved.status_code == 200, saved.text
    portrait = await approved_portrait(client, factory, store, headers, base)
    path = f"{base}/assets/scene-art-jobs"
    # Only approved images can stand for a character.
    unapproved = await client.post(path, headers=headers, json=scene_body(portrait["id"]))
    assert unapproved.status_code == 422, unapproved.text
    assert unapproved.json()["type"].endswith("invalid-scene-art-request")
    approved = await client.post(f"{base}/assets/{portrait['id']}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    body = scene_body(portrait["id"])
    created = await client.post(path, headers=headers, json=body)
    assert created.status_code == 202, created.text
    job = created.json()
    assert (job["purpose"], job["character_id"], job["count"]) == ("scene_art", "quen", 2)
    assert (job["width"], job["height"], job["output_width"]) == (1344, 768, 1344)
    assert job["reference_assets"] == [{"character_id": "quen", "asset_id": portrait["id"]}]
    assert job["ip_adapter_scale"] == 0.5 and job["ip_adapter_model"] is None
    assert job["appearance"] == body["scene"]
    assert job["prompt"].startswith(
        "1boy, male focus, solo, Quen sitting on the couch by the window at night, white hair, "
    )
    assert job["negative_prompt"].endswith("multiple boys")
    assert (await client.post(path, headers=headers, json=body)).json()["id"] == job["id"]
    changed = await client.post(path, headers=headers, json={**body, "scene": "on a beach"})
    assert changed.status_code == 409

    generator = FakeGenerator()
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=job["id"]
    )
    assert (await run_job(factory, store, payload, generator))["status"] == "completed"
    sent = generator.requests[0]
    reference = await client.get(f"{base}/assets/{portrait['id']}/content", headers=headers)
    assert sent.scene.references == (reference.content,) and sent.scene.scale == 0.5
    assert (sent.width, sent.height, sent.cutout, sent.inpaint) == (1344, 768, False, None)

    [listed] = (await client.get(path, headers=headers)).json()["jobs"]
    assert listed["status"] == "completed"
    assert listed["ip_adapter_model"] == f"{ADAPTER.repo}@{ADAPTER.revision}"
    cgs = listed["assets"]
    assert [item["name"] for item in cgs] == ["quen CG 1", "quen CG 2"]
    assert {(item["kind"], item["status"], item["character_id"]) for item in cgs} == {
        ("image", "candidate", "quen")
    }
    provenance = cgs[0]["provenance"]
    assert provenance["scene"] == body["scene"] and provenance["prompt"] == job["prompt"]
    assert provenance["references"] == [
        {"character_id": "quen", "asset_id": portrait["id"], "sha256": portrait["sha256"]}
    ]
    assert provenance["ip_adapter"] == {
        "model_repo": ADAPTER.repo,
        "model_revision": ADAPTER.revision,
        "license": ADAPTER.license,
        "scale": 0.5,
    }
    content = await client.get(f"{base}/assets/{cgs[0]['id']}/content", headers=headers)
    assert content.content[25] == 2, "a CG is an opaque scene"
    # An approved CG is an ordinary image for the stage's Event CG field.
    used = await client.post(f"{base}/assets/{cgs[0]['id']}/approve", headers=headers)
    assert (used.json()["kind"], used.json()["status"]) == ("image", "approved")
    shown = await client.get(f"{base}/assets", headers=headers, params={"kind": "image"})
    assert cgs[0]["id"] in {item["id"] for item in shown.json()["assets"]}
    # Portrait jobs never appear among the CG jobs.
    assert [item["id"] for item in (await client.get(path, headers=headers)).json()["jobs"]] == [
        job["id"]
    ]


async def test_scene_art_requests_are_checked_before_any_job_is_queued(studio):  # noqa: F811
    client, factory, _, headers, base, *_ = studio
    sprite = png(300, 500, 40, 7, alpha=True)
    uploaded = await client.post(
        f"{base}/assets",
        headers=headers,
        data={"kind": "sprite", "name": "Quen", "license": "Own work", "notice": "",
              "rights_declared": "true"},
        files={"file": ("quen.png", sprite, "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    sprite_id = uploaded.json()["id"]
    backdrop = await client.post(
        f"{base}/assets",
        headers=headers,
        data={"kind": "background", "name": "Harbor", "license": "Own work", "notice": "",
              "rights_declared": "true"},
        files={"file": ("harbor.png", png(1344, 768, 9, 2), "image/png")},
    )
    path = f"{base}/assets/scene-art-jobs"
    second = {"character_id": "mira", "reference_asset_id": sprite_id}
    for change, status in (
        ({"scene": ""}, 422),
        ({"scene": "x" * 601}, 422),
        ({"scene": "a nude beach"}, 422),
        ({"count": 5}, 422),
        ({"characters": []}, 422),
        # At most two characters, each once.
        ({"characters": [{"character_id": "quen", "reference_asset_id": sprite_id}, second,
                         {"character_id": "lina", "reference_asset_id": sprite_id}]}, 422),
        ({"characters": [second, second]}, 422),
        ({"characters": [{"character_id": "Not an id!", "reference_asset_id": sprite_id}]}, 422),
        ({"characters": [{"character_id": "quen", "reference_asset_id": str(uuid4())}]}, 404),
        ({"characters": [{"character_id": "quen",
                          "reference_asset_id": backdrop.json()["id"]}]}, 404),
    ):
        refused = await client.post(path, headers=headers, json={**scene_body(sprite_id), **change})
        assert refused.status_code == status, (change, refused.text)
    # The referenced character's own description passes the content policy too.
    blocked = {**QUEN, "appearance": "white hair, hentai"}
    saved = await client.put(f"{base}/characters/quen", headers=headers, json=blocked)
    assert saved.status_code == 200, saved.text
    refused = await client.post(path, headers=headers, json=scene_body(sprite_id))
    assert refused.status_code == 422 and "blocked" in refused.json()["detail"]
    async with factory() as session:
        count = await session.scalar(
            select(func.count(NarrativeImageJob.id)).where(NarrativeImageJob.purpose == "scene_art")
        )
    assert count == 0
    # A character without a profile is drawn from the reference and the scene alone.
    created = await client.post(
        path,
        headers=headers,
        json=scene_body(sprite_id, characters=[{"character_id": "lantern",
                                                "reference_asset_id": sprite_id}]),
    )
    assert created.status_code == 202, created.text
    assert created.json()["prompt"].startswith("solo, Quen sitting on the couch")
    # A discarded reference cannot start new CGs.
    await client.post(f"{base}/assets/{sprite_id}/discard", headers=headers)
    gone = await client.post(path, headers=headers, json=scene_body(sprite_id))
    assert gone.status_code == 404


async def test_a_scene_without_the_identity_adapter_fails_instead_of_storing_strangers(studio):  # noqa: F811
    client, factory, store, headers, base, *_ = studio
    sprite = png(300, 500, 40, 7, alpha=True)
    uploaded = await client.post(
        f"{base}/assets",
        headers=headers,
        data={"kind": "sprite", "name": "Quen", "license": "Own work", "notice": "",
              "rights_declared": "true"},
        files={"file": ("quen.png", sprite, "image/png")},
    )
    created = await client.post(
        f"{base}/assets/scene-art-jobs", headers=headers, json=scene_body(uploaded.json()["id"])
    )
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=created.json()["id"]
    )
    outcome = await run_job(factory, store, payload, FakeGenerator(skip_adapter=True))
    assert outcome["status"] == "failed"
    async with factory() as session:
        job = await session.get(NarrativeImageJob, UUID(created.json()["id"]))
        assert job is not None and job.error_code == "invalid_output"
    listed = (await client.get(f"{base}/image-jobs/{created.json()['id']}", headers=headers)).json()
    assert listed["assets"] == [] and listed["ip_adapter_model"] is None


LINA = {
    "base_version": 0,
    "appearance": "long black hair, blue eyes, hair ribbon, school uniform",
    "character_type": "girl",
    "framing": "full_body",
}


async def test_two_characters_each_keep_their_own_reference_and_side(studio):  # noqa: F811
    client, factory, store, headers, base, *_ = studio
    for character, profile in (("quen", QUEN), ("lina", LINA)):
        saved = await client.put(f"{base}/characters/{character}", headers=headers, json=profile)
        assert saved.status_code == 200, saved.text
    quen = await approved_portrait(client, factory, store, headers, base)
    await client.post(f"{base}/assets/{quen['id']}/approve", headers=headers)
    lina_bytes = png(320, 600, 60, 9, alpha=True)
    lina = (
        await client.post(
            f"{base}/assets",
            headers=headers,
            data={"kind": "sprite", "name": "Lina", "license": "Own work", "notice": "",
                  "rights_declared": "true", "character_id": "lina"},
            files={"file": ("lina.png", lina_bytes, "image/png")},
        )
    ).json()
    body = scene_body(
        quen["id"],
        scene="sitting on the couch together at night",
        characters=[{"character_id": "quen", "reference_asset_id": quen["id"]},
                    {"character_id": "lina", "reference_asset_id": lina["id"]}],
    )
    created = await client.post(f"{base}/assets/scene-art-jobs", headers=headers, json=body)
    assert created.status_code == 202, created.text
    job = created.json()
    assert job["character_id"] == "quen"
    assert job["prompt"].startswith("1boy, 1girl, sitting on the couch together at night, ")
    assert [item["character_id"] for item in job["reference_assets"]] == ["quen", "lina"]
    assert "white hair" in job["prompt"] and "black hair" in job["prompt"]
    generator = FakeGenerator()
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=job["id"]
    )
    assert (await run_job(factory, store, payload, generator))["status"] == "completed"
    sent = generator.requests[0].scene
    quen_bytes = (await client.get(f"{base}/assets/{quen['id']}/content", headers=headers)).content
    # The first reference conditions the left half, the second the right.
    assert sent.references == (quen_bytes, lina_bytes)
    [listed] = (await client.get(f"{base}/assets/scene-art-jobs", headers=headers)).json()["jobs"]
    cgs = listed["assets"]
    assert [item["name"] for item in cgs] == ["quen and lina CG 1", "quen and lina CG 2"]
    provenance = cgs[0]["provenance"]
    assert [item["character_id"] for item in provenance["references"]] == ["quen", "lina"]
    # The first character names the CG's group in the library.
    assert {item["character_id"] for item in cgs} == {"quen"}
