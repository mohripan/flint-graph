"""A pose can freeze one reviewed character adapter and one project style."""

from uuid import UUID, uuid4

import pytest
from test_narrative_character_adapters import look_request
from test_narrative_characters_api import studio  # noqa: F401

from flint_graph.config import get_settings
from flint_graph.main import app


async def test_character_adapter_role_requires_operator_rollout(studio):  # noqa: F811
    client, _, _, headers, base, *_ = studio
    _, look = await look_request(studio)
    response = await client.post(
        base + "/characters/mira/looks/pose-jobs",
        headers=headers,
        json={
            "look_id": look["id"],
            "pose": "walking",
            "transparent": False,
            "character_adapter": {"id": str(uuid4()), "strength": 0.5},
            "idempotency_key": str(uuid4()),
        },
    )
    assert response.status_code == 503, response.text
    assert response.json()["type"].endswith("pose-adapters-unavailable")


async def train(studio, body):  # noqa: F811
    import json
    import struct
    from dataclasses import replace

    from test_narrative_characters_api import Dispatcher, environment

    from flint_graph.application.narrative_image_workflow import ImageJobPayload
    from flint_graph.application.services.narrative_style_relay import relay_style_batch
    from flint_graph.infrastructure.narrative_stylegen import StyleTrainingResult
    from flint_graph.worker.activities.narrative_style import NarrativeStyleActivities

    client, factory, store, headers, base, *_ = studio
    response = await client.post(base + "/style-jobs", headers=headers, json=body)
    assert response.status_code == 202, response.text
    job = response.json()
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
    return (await client.get(base + "/style-jobs/" + job["id"], headers=headers)).json()


@pytest.fixture
async def ready(studio):  # noqa: F811
    body, look = await look_request(studio)
    configured = app.dependency_overrides[get_settings]().model_copy(
        update={"narrative_pose_max_adapters": 2}
    )
    app.dependency_overrides[get_settings] = lambda: configured
    character = await train(studio, body)
    project = await train(
        studio,
        {
            k: v
            for k, v in {**body, "idempotency_key": str(uuid4())}.items()
            if k != "character_look"
        },
    )
    pose = {
        "look_id": look["id"],
        "pose": "walking",
        "count": 1,
        "transparent": False,
        "idempotency_key": str(uuid4()),
        "character_adapter": {"id": character["id"], "strength": 0.6},
        "style_adapter": {"id": project["id"], "strength": 0.4},
    }
    return studio, pose, character, project


async def test_two_roles_freeze_replay_and_reach_the_pose_worker(ready):
    from test_narrative_characters_api import Dispatcher, FakeGenerator, environment

    from flint_graph.application.narrative_image_workflow import ImageJobPayload
    from flint_graph.application.services.narrative_image_relay import relay_image_batch
    from flint_graph.infrastructure.narrative_imagegen import ModelIdentity
    from flint_graph.narrative.poses import MODEL_REPO, MODEL_REVISION
    from flint_graph.worker.activities.narrative_pose import NarrativePoseActivities

    context, pose, character, project = ready
    client, factory, store, headers, base, *_ = context
    url = base + "/characters/mira/looks/pose-jobs"
    response = await client.post(url, headers=headers, json=pose)
    assert response.status_code == 202, response.text
    row = response.json()
    assert row["character_adapter"]["weights_sha256"] == character["weights_sha256"]
    assert row["character_adapter"]["kind"] == "character_look"
    assert row["style_adapter"]["weights_sha256"] == project["weights_sha256"]
    assert row["style_adapter"]["kind"] == "project_style"
    assert (await client.post(url, headers=headers, json=pose)).json()["job"]["id"] == row["job"][
        "id"
    ]
    changed = {**pose, "character_adapter": {**pose["character_adapter"], "strength": 0.5}}
    assert (await client.post(url, headers=headers, json=changed)).status_code == 409
    poses = Dispatcher()
    await relay_image_batch(factory, dispatcher=poses, poses=True)
    generator = FakeGenerator()
    generator.model = ModelIdentity(MODEL_REPO, MODEL_REVISION, "apache-2.0")
    generator.model_manifest_sha256 = "b" * 64
    generator.cutout_manifest_sha256 = None
    activity = NarrativePoseActivities(factory=factory, generator=generator, store=store)
    data = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=row["job"]["id"]
    )
    assert (await environment(data, poses.run_id).run(activity.run, data))["status"] == "completed"
    request = generator.requests[0]
    assert request.character_adapter.strength == 0.6 and request.style_adapter.strength == 0.4
    assert request.character_adapter.weights != request.style_adapter.weights
    result = (await client.get(url, headers=headers)).json()["jobs"][0]
    runtime = result["job"]["assets"][0]["provenance"]["runtime"]
    assert runtime["character_weights_sha256"] == character["weights_sha256"]
    assert runtime["style_weights_sha256"] == project["weights_sha256"]


@pytest.mark.parametrize(
    "change", ["duplicate", "swapped", "too_strong", "wrong_look", "foreign", "wrong_model"]
)
async def test_stack_refuses_incompatible_roles_and_versions(ready, change):
    from test_narrative_looks_api import look_body

    context, pose, character, project = ready
    client, factory, _, headers, base, *_ = context
    if change == "duplicate":
        pose["style_adapter"]["id"] = character["id"]
    elif change == "swapped":
        pose["character_adapter"]["id"], pose["style_adapter"]["id"] = (
            project["id"],
            character["id"],
        )
    elif change == "too_strong":
        pose["style_adapter"]["strength"] = 0.6
    elif change == "wrong_look":
        look = (
            await client.post(
                base + "/characters/mira/looks",
                headers=headers,
                json=look_body(
                    {"id": character["look"]["asset_id"]}, name="Another look", base_version=1
                ),
            )
        ).json()
        pose["look_id"] = look["id"]
    elif change == "foreign":
        pose["character_adapter"]["id"] = str(uuid4())
    else:
        from flint_graph.infrastructure.db.narrative_style_models import NarrativeStyleJob

        async with factory() as session:
            job = await session.get(NarrativeStyleJob, UUID(character["id"]))
            job.model_manifest_sha256 = "c" * 64
            await session.commit()
    result = await client.post(
        base + "/characters/mira/looks/pose-jobs", headers=headers, json=pose
    )
    assert result.status_code == (404 if change == "foreign" else 422), result.text


async def test_explicit_character_alone_replays_even_after_rollout_is_disabled(ready):
    context, pose, character, _ = ready
    client, _, _, headers, base, *_ = context
    pose.pop("style_adapter")
    url = base + "/characters/mira/looks/pose-jobs"
    first = await client.post(url, headers=headers, json=pose)
    assert first.status_code == 202, first.text
    assert first.json()["character_adapter"]["id"] == character["id"]
    assert first.json()["style_adapter"] is None
    configured = app.dependency_overrides[get_settings]().model_copy(
        update={"narrative_pose_max_adapters": 1}
    )
    app.dependency_overrides[get_settings] = lambda: configured
    replay = await client.post(url, headers=headers, json=pose)
    assert replay.status_code == 202 and replay.json()["job"]["id"] == first.json()["job"]["id"]
    pose["idempotency_key"] = str(uuid4())
    assert (await client.post(url, headers=headers, json=pose)).status_code == 503
