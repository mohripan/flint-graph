"""Anatomy review is independent of likeness, approval and training rights."""

import pytest
from test_narrative_character_adapters import look_request
from test_narrative_characters_api import studio  # noqa: F401


async def test_anatomy_review_persists_and_legacy_edits_cannot_clear_it(studio):  # noqa: F811
    client, _, _, headers, base, *_ = studio
    _, look = await look_request(studio)
    asset_id = look["asset"]["id"]
    url = base + f"/characters/mira/looks/{look['id']}/reviews/{asset_id}"
    initial = await client.get(url, headers=headers)
    assert initial.json()["anatomy"] == "unknown"
    body = {
        "base_version": 0,
        "identity": "same",
        "clothes": "same",
        "anatomy": "flawed",
        "anatomy_base_version": 0,
        "notes": "Extra boot",
    }
    saved = await client.post(url, headers=headers, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["anatomy"] == "flawed"
    legacy = {k: v for k, v in body.items() if k != "anatomy"}
    legacy["base_version"] = saved.json()["version"]
    legacy["notes"] = "Identity matched; anatomy still needs correction"
    updated = await client.post(url, headers=headers, json=legacy)
    assert updated.status_code == 200 and updated.json()["anatomy"] == "flawed"
    assert (await client.post(url, headers=headers, json=body)).status_code == 409
    flags = (
        await client.get(base + "/look-reviews", headers=headers, params={"asset_id": asset_id})
    ).json()["reviews"]
    assert flags[0]["anatomy"] == "flawed" and flags[0]["candidate_sha256"] == look["source_sha256"]
    # Approval remains a separate creator choice.
    assert (
        await client.post(base + f"/assets/{asset_id}/approve", headers=headers)
    ).status_code == 200


async def verdict(context, look, asset_id, anatomy):
    client, _, _, headers, base, *_ = context
    url = base + f"/characters/mira/looks/{look['id']}/reviews/{asset_id}"
    current = (await client.get(url, headers=headers)).json()
    version = current["version"]
    return await client.post(
        url,
        headers=headers,
        json={
            "base_version": version,
            "identity": "same",
            "clothes": "same",
            "anatomy": anatomy,
            "anatomy_base_version": current["anatomy_version"],
            "notes": "Manual QA",
        },
    )


@pytest.mark.parametrize("target", ["character", "project"])
async def test_flawed_sources_cannot_train_until_the_review_is_revised(studio, target):  # noqa: F811
    client, _, _, headers, base, *_ = studio
    body, look = await look_request(studio)
    if target == "project":
        body.pop("character_look")
    source = body["images"][0]["asset_id"]
    assert (await verdict(studio, look, source, "flawed")).status_code == 200
    blocked = await client.post(base + "/style-jobs", headers=headers, json=body)
    assert blocked.status_code == 422, blocked.text
    assert blocked.json()["type"].endswith("anatomy-review-failed")
    assert (await verdict(studio, look, source, "acceptable")).status_code == 200
    accepted = await client.post(base + "/style-jobs", headers=headers, json=body)
    assert accepted.status_code == 202, accepted.text
    assert (await verdict(studio, look, source, "flawed")).status_code == 200
    # An idempotent replay returns the admitted history; execution rechecks the source.
    replay = await client.post(base + "/style-jobs", headers=headers, json=body)
    assert replay.status_code == 202 and replay.json()["id"] == accepted.json()["id"]


@pytest.mark.parametrize("when", ["before", "during", "publication"])
async def test_worker_rechecks_anatomy_before_training_and_publication(studio, when):  # noqa: F811
    import json
    import struct
    from dataclasses import replace

    from test_narrative_characters_api import Dispatcher, environment

    from flint_graph.application.narrative_image_workflow import ImageJobPayload
    from flint_graph.application.services.narrative_style_relay import relay_style_batch
    from flint_graph.infrastructure.narrative_stylegen import StyleTrainingResult
    from flint_graph.worker.activities.narrative_style import NarrativeStyleActivities

    client, factory, store, headers, base, *_ = studio
    body, look = await look_request(studio)
    source = body["images"][0]["asset_id"]
    job = (await client.post(base + "/style-jobs", headers=headers, json=body)).json()
    dispatcher = Dispatcher()
    assert await relay_style_batch(factory, dispatcher=dispatcher) == 1
    if when == "before":
        await verdict(studio, look, source, "flawed")
    calls, puts = [], []

    class Trainer:
        model_hash = "b" * 64

        async def train(self, request, *, on_progress):
            calls.append(request)
            assert when != "before", "Known flawed sources must not reach the trainer"
            if when == "during":
                await verdict(studio, look, source, "flawed")
                await on_progress(1)
            header = {
                "__metadata__": {
                    "format": "pt",
                    "model_manifest_sha256": "b" * 64,
                    "dataset_sha256": request.dataset_hash,
                    "recipe_sha256": request.recipe_hash,
                }
            }
            for letter, shape, offsets in [("A", [4, 8], [0, 128]), ("B", [8, 4], [128, 256])]:
                header["transformer.transformer_blocks.0.attn.to_q.lora_" + letter + ".weight"] = {
                    "dtype": "F32",
                    "shape": shape,
                    "data_offsets": offsets,
                }
            raw = json.dumps(header).encode()
            blob = struct.pack("<Q", len(raw)) + raw + struct.pack("<64f", *([0.25] * 64))
            return StyleTrainingResult(blob, [0.5] * 20, {"seconds": "1"})

    async def put(key, data, *, expected_sha256):
        puts.append(key)
        if when == "publication":
            assert (await verdict(studio, look, source, "flawed")).status_code == 200
        store.objects[key] = data

    store.put_private_adapter = put
    activity = NarrativeStyleActivities(factory=factory, trainer=Trainer(), store=store)
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=job["id"]
    )
    env = environment(payload, dispatcher.run_id)
    env.info = replace(
        env.info,
        workflow_id="narrative-style-" + job["id"],
        workflow_type="NarrativeStyleJobWorkflow",
        activity_type="run_narrative_style_job",
    )
    assert (await env.run(activity.run, payload))["status"] == "failed"
    result = (await client.get(base + "/style-jobs/" + job["id"], headers=headers)).json()
    assert result["error_code"] == "anatomy_review_failed" and result["weights_sha256"] is None
    if when == "before":
        assert not calls
    if when != "publication":
        assert not puts


async def test_reuploading_the_same_flawed_image_cannot_bypass_its_review(studio):  # noqa: F811
    from test_narrative_looks_api import approved

    client, _, _, headers, base, *_ = studio
    body, look = await look_request(studio)
    old_id = body["images"][1]["asset_id"]
    assert (await verdict(studio, look, old_id, "flawed")).status_code == 200
    assert (
        await client.post(base + f"/assets/{old_id}/discard", headers=headers)
    ).status_code == 200
    replacement = await approved(client, headers, base, shade=31)
    assert replacement["id"] != old_id
    flags = (
        await client.get(
            base + "/look-reviews", headers=headers, params={"asset_id": replacement["id"]}
        )
    ).json()["reviews"]
    assert flags and flags[0]["anatomy"] == "flawed"
    body["images"][1]["asset_id"] = replacement["id"]
    blocked = await client.post(base + "/style-jobs", headers=headers, json=body)
    assert blocked.status_code == 422 and blocked.json()["type"].endswith("anatomy-review-failed")

    # The shared verdict can be deliberately revised through the live copy.
    assert (await verdict(studio, look, replacement["id"], "acceptable")).status_code == 200
    accepted = await client.post(base + "/style-jobs", headers=headers, json=body)
    assert accepted.status_code == 202, accepted.text


async def test_a_stale_dialog_for_another_look_cannot_clear_the_shared_anatomy_verdict(studio):  # noqa: F811
    from test_narrative_looks_api import look_body

    client, _, _, headers, base, *_ = studio
    _, look = await look_request(studio)
    other = (
        await client.post(
            base + "/characters/mira/looks",
            headers=headers,
            json=look_body(look["asset"], name="Another reviewed look", base_version=1),
        )
    ).json()
    source = look["asset"]["id"]
    url = base + f"/characters/mira/looks/{other['id']}/reviews/{source}"
    stale = (await client.get(url, headers=headers)).json()
    assert (await verdict(studio, look, source, "flawed")).status_code == 200
    result = await client.post(
        url,
        headers=headers,
        json={
            "base_version": stale["version"],
            "identity": "same",
            "clothes": "same",
            "anatomy": "unknown",
            "anatomy_base_version": stale["anatomy_version"],
        },
    )
    assert result.status_code == 409 and result.json()["type"].endswith("stale-anatomy-review")
    current = (await client.get(url, headers=headers)).json()
    assert current["anatomy"] == "flawed" and current["anatomy_version"] == 1
    assert (await verdict(studio, other, source, "acceptable")).status_code == 200
    original = (
        await client.get(
            base + f"/characters/mira/looks/{look['id']}/reviews/{source}", headers=headers
        )
    ).json()
    assert original["anatomy"] == "acceptable" and original["anatomy_version"] == 2


async def test_anatomy_review_keeps_workspace_and_member_boundaries(studio):  # noqa: F811
    from test_narrative_voice_references_api import add_member

    client, _, _, headers, base, workspace, oidc_auth = studio
    _, look = await look_request(studio)
    url = base + f"/characters/mira/looks/{look['id']}/reviews/{look['asset']['id']}"
    foreign = (
        await client.post("/v1/workspaces", headers=headers, json={"name": "Foreign anatomy QA"})
    ).json()
    assert (
        await client.get(url, headers={**headers, "X-Tenant-ID": foreign["id"]})
    ).status_code == 404
    await add_member(client, headers, workspace, "anatomy-viewer", "viewer")
    viewer = {**headers, "Authorization": "Bearer " + oidc_auth("anatomy-viewer")}
    assert (await client.get(url, headers=viewer)).status_code == 200
    body = {
        "base_version": 0,
        "identity": "same",
        "clothes": "same",
        "anatomy": "flawed",
        "anatomy_base_version": 0,
    }
    assert (await client.post(url, headers=viewer, json=body)).status_code == 403
    assert (
        await client.post(url, headers=headers, json={**body, "anatomy": "maybe"})
    ).status_code == 422
