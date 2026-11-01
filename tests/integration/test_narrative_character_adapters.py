from uuid import uuid4

import pytest
from test_narrative_characters_api import studio  # noqa: F401
from test_narrative_looks_api import approved, look_body
from test_narrative_styles_api import request_body


async def look_request(studio):  # noqa: F811
    client, _, _, headers, base, *_ = studio
    body = await request_body(studio)
    asset = await approved(client, headers, base, shade=30)
    look = (
        await client.post(base + "/characters/mira/looks", headers=headers, json=look_body(asset))
    ).json()
    body["character_look"] = {
        "character_id": "mira",
        "look_id": look["id"],
        "same_look_confirmed": True,
        "anatomy_reviewed": True,
    }
    return body, look


async def test_character_training_pins_approved_look_and_preserves_project_style_replays(studio):  # noqa: F811
    client, _, _, headers, base, *_ = studio
    body, look = await look_request(studio)
    result = await client.post(base + "/style-jobs", headers=headers, json=body)
    assert result.status_code == 202, result.text
    row = result.json()
    assert row["kind"] == "character_look" and row["look"]["sha256"] == look["sha256"]
    assert all(item["look_sha256"] == look["sha256"] for item in row["images"])
    listed = (await client.get(base + "/style-jobs", headers=headers)).json()["jobs"]
    assert listed[0]["look"]["id"] == look["id"]
    replay = await client.post(base + "/style-jobs", headers=headers, json=body)
    assert replay.status_code == 202 and replay.json()["id"] == row["id"]
    conflict = await client.post(
        base + "/style-jobs",
        headers=headers,
        json={k: v for k, v in body.items() if k != "character_look"},
    )
    assert conflict.status_code == 409


@pytest.mark.parametrize(
    "change", ["unconfirmed", "anatomy_unreviewed", "missing_base", "other_character"]
)
async def test_character_training_requires_same_look_confirmation_and_base(studio, change):  # noqa: F811
    client, _, _, headers, base, *_ = studio
    body, _look = await look_request(studio)
    if change == "unconfirmed":
        body["character_look"]["same_look_confirmed"] = False
    elif change == "anatomy_unreviewed":
        body["character_look"]["anatomy_reviewed"] = False
    elif change == "missing_base":
        extra = await approved(client, headers, base, shade=60)
        body["images"][0]["asset_id"] = extra["id"]
    else:
        body["character_look"]["character_id"] = "other"
    result = await client.post(base + "/style-jobs", headers=headers, json=body)
    assert result.status_code in (404, 422), result.text


async def test_trained_character_version_only_renders_its_frozen_look(studio):  # noqa: F811
    import json
    import struct
    from dataclasses import replace

    from test_narrative_characters_api import Dispatcher, FakeGenerator, environment

    from flint_graph.application.narrative_image_workflow import ImageJobPayload
    from flint_graph.application.services.narrative_image_relay import relay_image_batch
    from flint_graph.application.services.narrative_style_relay import relay_style_batch
    from flint_graph.infrastructure.narrative_imagegen import ModelIdentity
    from flint_graph.infrastructure.narrative_stylegen import StyleTrainingResult
    from flint_graph.narrative.poses import MODEL_REPO, MODEL_REVISION
    from flint_graph.worker.activities.narrative_pose import NarrativePoseActivities
    from flint_graph.worker.activities.narrative_style import NarrativeStyleActivities

    client, factory, store, headers, base, *_ = studio
    body, look = await look_request(studio)
    job = (await client.post(base + "/style-jobs", headers=headers, json=body)).json()
    dispatcher = Dispatcher()
    await relay_style_batch(factory, dispatcher=dispatcher)

    class Trainer:
        model_hash = "b" * 64

        async def train(self, request, *, on_progress):
            await on_progress(20)
            header = {
                "__metadata__": {
                    "format": "pt",
                    "model_manifest_sha256": "b" * 64,
                    "dataset_sha256": request.dataset_hash,
                    "recipe_sha256": request.recipe_hash,
                }
            }
            for letter, shape, offset in [("A", [4, 8], [0, 128]), ("B", [8, 4], [128, 256])]:
                header["transformer.transformer_blocks.0.attn.to_q.lora_" + letter + ".weight"] = {
                    "dtype": "F32",
                    "shape": shape,
                    "data_offsets": offset,
                }
            raw = json.dumps(header).encode()
            blob = struct.pack("<Q", len(raw)) + raw + struct.pack("<64f", *([0.25] * 64))
            return StyleTrainingResult(blob, [0.5] * 20, {"seconds": "1"})

    async def put(key, data, *, expected_sha256):
        store.objects[key] = data

    store.put_private_adapter = put
    work = NarrativeStyleActivities(factory=factory, trainer=Trainer(), store=store)
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
    assert (await env.run(work.run, payload))["status"] == "completed"
    other = (
        await client.post(
            base + "/characters/mira/looks",
            headers=headers,
            json=look_body(
                {"id": look["asset"]["id"]},
                name="Other outfit",
                base_version=1,
                clothing_tags=["yellow raincoat"],
            ),
        )
    ).json()
    pose = {
        "look_id": other["id"],
        "pose": "standing",
        "count": 1,
        "transparent": False,
        "style_adapter": {"id": job["id"], "strength": 0.5},
        "idempotency_key": str(uuid4()),
    }
    wrong = await client.post(base + "/characters/mira/looks/pose-jobs", headers=headers, json=pose)
    assert wrong.status_code == 422, wrong.text
    pose["look_id"] = look["id"]
    pose["idempotency_key"] = str(uuid4())
    accepted = await client.post(
        base + "/characters/mira/looks/pose-jobs", headers=headers, json=pose
    )
    assert accepted.status_code == 202, accepted.text
    poses = Dispatcher()
    await relay_image_batch(factory, dispatcher=poses, poses=True)
    generator = FakeGenerator()
    generator.model = ModelIdentity(MODEL_REPO, MODEL_REVISION, "apache-2.0")
    generator.model_manifest_sha256 = "b" * 64
    generator.cutout_manifest_sha256 = None
    activity = NarrativePoseActivities(factory=factory, generator=generator, store=store)
    data = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=accepted.json()["job"]["id"]
    )
    assert (await environment(data, poses.run_id).run(activity.run, data))["status"] == "completed"
    assert generator.requests[0].style_adapter is not None
    # An admitted retry must stop if its reviewed base is no longer approved.
    await client.post(base + "/assets/" + look["asset"]["id"] + "/discard", headers=headers)
    retry = await client.post(
        base + "/characters/mira/looks/pose-jobs",
        headers=headers,
        json={**pose, "idempotency_key": str(uuid4())},
    )
    assert retry.status_code == 422
