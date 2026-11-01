from uuid import uuid4

import pytest
from test_narrative_characters_api import studio  # noqa: F401
from test_narrative_looks_api import approved

from flint_graph.config import get_settings
from flint_graph.main import app


async def request_body(studio):  # noqa: F811
    client, _, _, headers, base, *_ = studio
    configured = app.dependency_overrides[get_settings]().model_copy(
        update={
            "narrative_style_training_enabled": True,
            "narrative_pose_generation_enabled": True,
            "narrative_pose_model_manifest_sha256": "b" * 64,
        }
    )
    app.dependency_overrides[get_settings] = lambda: configured
    assets = [await approved(client, headers, base, shade=n) for n in range(30, 34)]
    return dict(
        name="Evening palette",
        images=[
            {"asset_id": a["id"], "caption": "white hair, navy coat, red scarf, standing"}
            for a in assets
        ],
        rights_confirmed=True,
        steps=20,
        seed=42,
        idempotency_key=str(uuid4()),
    )


async def test_style_training_freezes_dataset_and_replays_without_second_job(studio, tmp_path):  # noqa: F811
    client, _, _, headers, base, *_ = studio
    body = await request_body(studio)
    response = await client.post(base + "/style-jobs", headers=headers, json=body)
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["status"] == "queued" and job["steps"] == 20 and job["progress"] == 0
    assert len(job["images"]) == 4 and len(job["dataset_sha256"]) == 64
    assert len(job["images"][0]["policy_sha256"]) == 64
    policy = tmp_path / "policy.toml"
    policy.write_text('version = 1\nnegative = []\nblocked = ["unwanted"]\n')
    configured = app.dependency_overrides[get_settings]().model_copy(
        update={"narrative_image_content_policy": str(policy)}
    )
    app.dependency_overrides[get_settings] = lambda: configured
    assert "weights_key" not in job and job["weights_sha256"] is None
    replay = await client.post(base + "/style-jobs", headers=headers, json=body)
    assert replay.status_code == 202 and replay.json()["id"] == job["id"]
    conflict = await client.post(base + "/style-jobs", headers=headers, json={**body, "seed": 43})
    assert conflict.status_code == 409
    second = await client.post(
        base + "/style-jobs", headers=headers, json={**body, "idempotency_key": str(uuid4())}
    )
    assert second.status_code == 429
    cancelled = await client.post(base + "/style-jobs/" + job["id"] + "/cancel", headers=headers)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"


@pytest.mark.parametrize(
    "change",
    [
        {"rights_confirmed": False},
        {"steps": True},
        {"images": []},
        {"images": [{"asset_id": str(uuid4()), "caption": "x"}] * 4},
    ],
)
async def test_style_training_rejects_unreviewed_or_unbounded_requests(studio, change):  # noqa: F811
    client, _, _, headers, base, *_ = studio
    body = await request_body(studio)
    response = await client.post(base + "/style-jobs", headers=headers, json={**body, **change})
    assert response.status_code in (404, 422), response.text


async def test_style_worker_registers_fences_and_publishes_private_weights(studio):  # noqa: F811
    import json
    import struct
    from dataclasses import replace

    from test_narrative_characters_api import Dispatcher, environment

    from flint_graph.application.narrative_image_workflow import ImageJobPayload
    from flint_graph.application.services.narrative_style_relay import relay_style_batch
    from flint_graph.infrastructure.narrative_stylegen import StyleTrainingResult
    from flint_graph.worker.activities.narrative_style import NarrativeStyleActivities

    def weights():
        header = {
            "__metadata__": {
                "format": "pt",
                "model_manifest_sha256": "b" * 64,
                "dataset_sha256": "c" * 64,
                "recipe_sha256": "d" * 64,
            }
        }
        for letter, shape, offset in [("A", [4, 8], [0, 128]), ("B", [8, 4], [128, 256])]:
            header["transformer.transformer_blocks.0.attn.to_q.lora_" + letter + ".weight"] = {
                "dtype": "F32",
                "shape": shape,
                "data_offsets": offset,
            }
        raw = json.dumps(header).encode()
        return struct.pack("<Q", len(raw)) + raw + struct.pack("<64f", *([0.25] * 64))

    client, factory, store, headers, base, *_ = studio
    body = await request_body(studio)
    created = (await client.post(base + "/style-jobs", headers=headers, json=body)).json()
    dispatcher = Dispatcher()
    assert await relay_style_batch(factory, dispatcher=dispatcher) == 1
    calls = []

    class Trainer:
        model_hash = "b" * 64

        async def train(self, request, *, on_progress):
            calls.append(request)
            await on_progress(10)
            # These bytes are deliberately a small protocol fixture, not real training.
            blob = (
                weights()
                .replace(b"c" * 64, request.dataset_hash.encode())
                .replace(b"d" * 64, request.recipe_hash.encode())
            )
            return StyleTrainingResult(blob, [0.5] * 20, {"seconds": "1"})

    async def put(key, data, *, expected_sha256):
        store.objects[key] = data

    store.put_private_adapter = put
    activities = NarrativeStyleActivities(factory=factory, trainer=Trainer(), store=store)
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=created["id"]
    )
    env = environment(payload, dispatcher.run_id)
    env.info = replace(
        env.info,
        workflow_id="narrative-style-" + created["id"],
        workflow_type="NarrativeStyleJobWorkflow",
        activity_type="run_narrative_style_job",
    )
    outcome = await env.run(activities.run, payload)
    assert outcome["status"] == "completed"
    row = (await client.get(base + "/style-jobs/" + created["id"], headers=headers)).json()
    assert row["status"] == "completed" and row["progress"] == 20 and row["weights_sha256"]
    assert len(calls) == 1 and len(calls[0].images) == 4
    assert all("/style-adapters/" in key for key in store.objects if key.endswith(".safetensors"))
    replay = await env.run(activities.run, payload)
    assert replay["status"] == "completed" and len(calls) == 1

    from test_narrative_looks_api import look_body

    asset = await approved(client, headers, base, shade=45)
    look = (
        await client.post(base + "/characters/mira/looks", headers=headers, json=look_body(asset))
    ).json()
    pose_body = {
        "look_id": look["id"],
        "pose": "sitting, hands in lap",
        "count": 1,
        "transparent": False,
        "idempotency_key": str(uuid4()),
        "style_adapter": {"id": created["id"], "strength": 0.5},
    }
    pose = await client.post(
        base + "/characters/mira/looks/pose-jobs", headers=headers, json=pose_body
    )
    assert pose.status_code == 202, pose.text
    assert pose.json()["style_adapter"]["weights_sha256"] == row["weights_sha256"]
    from test_narrative_characters_api import FakeGenerator

    from flint_graph.application.services.narrative_image_relay import relay_image_batch
    from flint_graph.infrastructure.narrative_imagegen import ModelIdentity
    from flint_graph.narrative.poses import MODEL_REPO, MODEL_REVISION
    from flint_graph.worker.activities.narrative_pose import NarrativePoseActivities

    poses = Dispatcher()
    await relay_image_batch(factory, dispatcher=poses, poses=True)
    generator = FakeGenerator()
    generator.model = ModelIdentity(MODEL_REPO, MODEL_REVISION, "apache-2.0")
    generator.model_manifest_sha256 = "b" * 64
    generator.cutout_manifest_sha256 = None
    running = NarrativePoseActivities(factory=factory, generator=generator, store=store)
    pose_payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=pose.json()["job"]["id"]
    )
    result = await environment(pose_payload, poses.run_id).run(running.run, pose_payload)
    assert result["status"] == "completed"
    assert generator.requests[0].style_adapter.strength == 0.5
    assert generator.requests[0].style_adapter.weights == next(
        data for key, data in store.objects.items() if key.endswith(".safetensors")
    )


async def test_cancelled_training_cannot_publish_or_reopen_from_a_stale_run(studio):  # noqa: F811
    import asyncio
    from dataclasses import replace

    from test_narrative_characters_api import Dispatcher, environment

    from flint_graph.application.narrative_image_workflow import ImageJobPayload
    from flint_graph.application.services.narrative_style_relay import relay_style_batch
    from flint_graph.worker.activities.narrative_style import NarrativeStyleActivities

    client, factory, store, headers, base, *_ = studio
    body = await request_body(studio)
    created = (await client.post(base + "/style-jobs", headers=headers, json=body)).json()
    dispatcher = Dispatcher()
    await relay_style_batch(factory, dispatcher=dispatcher)
    began = asyncio.Event()
    release = asyncio.Event()

    class Trainer:
        model_hash = "b" * 64

        async def train(self, request, *, on_progress):
            began.set()
            await release.wait()
            await on_progress(20)
            raise AssertionError("cancelled work must stop before output")

    async def forbidden(*args, **kwargs):
        raise AssertionError("cancelled work must never publish")

    store.put_private_adapter = forbidden
    activity = NarrativeStyleActivities(factory=factory, trainer=Trainer(), store=store)
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=created["id"]
    )
    env = environment(payload, dispatcher.run_id)
    env.info = replace(
        env.info,
        workflow_id="narrative-style-" + created["id"],
        workflow_type="NarrativeStyleJobWorkflow",
        activity_type="run_narrative_style_job",
    )
    running = asyncio.create_task(env.run(activity.run, payload))
    await asyncio.wait_for(began.wait(), 5)
    cancelled = await client.post(
        base + "/style-jobs/" + created["id"] + "/cancel", headers=headers
    )
    assert cancelled.status_code == 200 and cancelled.json()["cancel_requested"]
    release.set()
    result = await running
    assert result["status"] == "cancelled"
    stale = environment(payload, uuid4())
    stale.info = replace(env.info, workflow_run_id=str(uuid4()))
    assert (await stale.run(activity.run, payload))["status"] == "stale"
    row = (await client.get(base + "/style-jobs/" + created["id"], headers=headers)).json()
    assert row["status"] == "cancelled" and row["weights_sha256"] is None


async def test_style_metadata_and_training_are_workspace_scoped(studio):  # noqa: F811
    client, _, _, headers, base, workspace, oidc_auth = studio
    body = await request_body(studio)
    job = (await client.post(base + "/style-jobs", headers=headers, json=body)).json()
    foreign = (
        await client.post("/v1/workspaces", headers=headers, json={"name": "Style isolation"})
    ).json()
    elsewhere = {**headers, "X-Tenant-ID": foreign["id"]}
    assert (
        await client.get(base + "/style-jobs/" + job["id"], headers=elsewhere)
    ).status_code == 404
    assert (
        await client.post(base + "/style-jobs/" + job["id"] + "/cancel", headers=elsewhere)
    ).status_code == 404
    await client.post(
        f"/v1/workspaces/{workspace['id']}/members",
        headers=headers,
        json={
            "oidc_issuer": "https://keycloak.example/realms/flintgraph",
            "oidc_subject": "style-viewer",
            "role": "viewer",
        },
    )
    viewer = {**headers, "Authorization": "Bearer " + oidc_auth("style-viewer")}
    assert (await client.get(base + "/style-jobs", headers=viewer)).status_code == 200
    assert (await client.post(base + "/style-jobs", headers=viewer, json=body)).status_code == 403
    assert (
        await client.post(base + "/style-jobs/" + job["id"] + "/cancel", headers=viewer)
    ).status_code == 403


async def test_recovery_only_closes_its_registered_finished_run(studio):  # noqa: F811
    from datetime import timedelta

    from test_narrative_characters_api import Dispatcher

    from flint_graph.application.services.narrative_style_relay import (
        recover_style_jobs,
        relay_style_batch,
    )

    client, factory, _, headers, base, *_ = studio
    body = await request_body(studio)
    job = (await client.post(base + "/style-jobs", headers=headers, json=body)).json()
    live = Dispatcher(closed=False)
    await relay_style_batch(factory, dispatcher=live)
    assert await recover_style_jobs(factory, dispatcher=live, older_than=timedelta(0)) == 0
    closed = Dispatcher(closed=True)
    closed.run_id = live.run_id
    assert await recover_style_jobs(factory, dispatcher=closed, older_than=timedelta(0)) == 1
    row = (await client.get(base + "/style-jobs/" + job["id"], headers=headers)).json()
    assert row["status"] == "failed" and row["error_code"] == "worker_interrupted"
    assert (
        await client.post(
            base + "/style-jobs", headers=headers, json={**body, "idempotency_key": str(uuid4())}
        )
    ).status_code == 202
