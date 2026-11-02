"""Local repairs retain their source and the creator's selected region."""

from uuid import uuid4

import pytest
from test_narrative_characters_api import studio  # noqa: F401
from test_narrative_pose_adapters import ready  # noqa: F401


async def rendered(context, existing=None):
    from test_narrative_characters_api import Dispatcher, FakeGenerator, environment
    from test_narrative_poses_api import admitted

    from flint_graph.application.narrative_image_workflow import ImageJobPayload
    from flint_graph.application.services.narrative_image_relay import relay_image_batch
    from flint_graph.config import get_settings
    from flint_graph.infrastructure.narrative_imagegen import ModelIdentity
    from flint_graph.main import app
    from flint_graph.narrative.poses import MODEL_REPO, MODEL_REVISION
    from flint_graph.worker.activities.narrative_pose import NarrativePoseActivities

    client, factory, store, headers, *_ = context
    if existing:
        url, row = existing
    else:
        url, _, row = await admitted(context)
    dispatcher = Dispatcher()
    await relay_image_batch(factory, dispatcher=dispatcher, poses=True)
    generator = FakeGenerator()
    generator.model = ModelIdentity(MODEL_REPO, MODEL_REVISION, "apache-2.0")
    generator.model_manifest_sha256 = "b" * 64
    generator.cutout_manifest_sha256 = None
    activity = NarrativePoseActivities(factory=factory, generator=generator, store=store)
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=row["job"]["id"]
    )
    assert (await environment(payload, dispatcher.run_id).run(activity.run, payload))[
        "status"
    ] == "completed"
    source = (await client.get(url + "/pose-jobs", headers=headers)).json()["jobs"][0]
    settings = app.dependency_overrides[get_settings]().model_copy(
        update={
            "narrative_pose_repairs_enabled": True,
            "narrative_pose_max_references": 2,
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings
    return url, source


async def test_repairs_are_an_explicit_operator_rollout(studio):  # noqa: F811
    client, _, _, headers, base, *_ = studio
    response = await client.post(
        base + "/characters/mira/looks/pose-repairs",
        headers=headers,
        json={
            "asset_id": str(uuid4()),
            "box": [100, 100, 180, 220],
            "instruction": "a natural hand resting on the thigh",
            "count": 1,
            "idempotency_key": str(uuid4()),
        },
    )
    assert response.status_code == 503, response.text
    assert response.json()["type"].endswith("pose-repairs-unavailable")


async def test_a_candidate_can_be_repaired_without_approval_and_replays_keep_the_frozen_region(
    studio,  # noqa: F811
):
    from flint_graph.config import get_settings
    from flint_graph.main import app

    client, _, _, headers, *_ = studio
    url, source = await rendered(studio)
    asset = source["job"]["assets"][0]
    assert asset["status"] == "candidate"
    body = {
        "asset_id": asset["id"],
        "box": [400, 500, 560, 660],
        "instruction": "a natural left hand resting on the thigh",
        "count": 2,
        "idempotency_key": str(uuid4()),
    }
    response = await client.post(url + "/pose-repairs", headers=headers, json=body)
    assert response.status_code == 202, response.text
    row = response.json()
    assert row["repair"]["source_asset_id"] == asset["id"]
    assert row["repair"]["source_sha256"] == asset["sha256"]
    assert row["repair"]["box"] == [400, 500, 560, 660]
    assert [ref["asset_id"] for ref in row["references"]] == [
        asset["id"],
        source["look"]["asset_id"],
    ]
    assert row["look"]["sha256"] == source["look"]["sha256"]
    settings = app.dependency_overrides[get_settings]().model_copy(
        update={"narrative_pose_repairs_enabled": False}
    )
    app.dependency_overrides[get_settings] = lambda: settings
    replay = await client.post(url + "/pose-repairs", headers=headers, json=body)
    assert replay.status_code == 202 and replay.json()["job"]["id"] == row["job"]["id"]
    changed = await client.post(
        url + "/pose-repairs", headers=headers, json={**body, "box": [400, 500, 570, 660]}
    )
    assert changed.status_code == 409


@pytest.mark.parametrize(
    "box",
    [
        [-1, 0, 50, 50],
        [0, 0, 800, 50],
        [0, 0, 10, 100],
        [0, 0, 768, 1152],
        [100, 100, 50, 150],
        [0, 0, True, 50],
    ],
)
async def test_repairs_refuse_invalid_or_overly_large_regions(studio, box):  # noqa: F811
    client, _, _, headers, *_ = studio
    url, source = await rendered(studio)
    response = await client.post(
        url + "/pose-repairs",
        headers=headers,
        json={
            "asset_id": source["job"]["assets"][0]["id"],
            "box": box,
            "instruction": "a natural hand",
            "idempotency_key": str(uuid4()),
        },
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("discarded", [False, True])
async def test_repair_worker_loads_the_exact_candidate_and_the_approved_look(studio, discarded):  # noqa: F811
    from hashlib import sha256

    from test_narrative_characters_api import Dispatcher, FakeGenerator, environment

    from flint_graph.application.narrative_image_workflow import ImageJobPayload
    from flint_graph.application.services.narrative_image_relay import relay_image_batch
    from flint_graph.infrastructure.narrative_imagegen import ImageGenerationError, ModelIdentity
    from flint_graph.narrative.poses import MODEL_REPO, MODEL_REVISION
    from flint_graph.worker.activities.narrative_pose import NarrativePoseActivities

    client, factory, store, headers, *_ = studio
    url, source = await rendered(studio)
    asset = source["job"]["assets"][0]
    response = await client.post(
        url + "/pose-repairs",
        headers=headers,
        json={
            "asset_id": asset["id"],
            "box": [400, 500, 560, 660],
            "instruction": "a natural hand",
            "idempotency_key": str(uuid4()),
        },
    )
    assert response.status_code == 202, response.text
    if discarded:
        result = await client.post(
            studio[4] + "/assets/" + asset["id"] + "/discard", headers=headers
        )
        assert result.status_code == 200
    dispatcher = Dispatcher()
    await relay_image_batch(factory, dispatcher=dispatcher, poses=True)

    class Capture(FakeGenerator):
        async def generate(self, request, *, on_progress):
            self.requests.append(request)
            raise ImageGenerationError("cutout_failed")

    generator = Capture()
    generator.model = ModelIdentity(MODEL_REPO, MODEL_REVISION, "apache-2.0")
    generator.model_manifest_sha256 = "b" * 64
    generator.cutout_manifest_sha256 = None
    activity = NarrativePoseActivities(factory=factory, generator=generator, store=store)
    data = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=response.json()["job"]["id"]
    )
    assert (await environment(data, dispatcher.run_id).run(activity.run, data))[
        "status"
    ] == "failed"
    if discarded:
        assert generator.requests == []
        return
    request = generator.requests[0]
    assert request.repair is not None and request.repair.box == (400, 500, 560, 660)
    assert sha256(request.reference).hexdigest() == asset["sha256"]
    assert len(request.additional_references) == 1
    assert sha256(request.additional_references[0]).hexdigest() == source["look"]["source_sha256"]


async def test_repairs_inherit_both_exact_adapter_versions(ready):  # noqa: F811
    context, pose, character, style = ready
    client, _, _, headers, base, *_ = context
    url = base + "/characters/mira/looks"
    original = await client.post(url + "/pose-jobs", headers=headers, json=pose)
    assert original.status_code == 202, original.text
    _, source = await rendered(context, (url, original.json()))
    response = await client.post(
        url + "/pose-repairs",
        headers=headers,
        json={
            "asset_id": source["job"]["assets"][0]["id"],
            "box": [400, 500, 560, 660],
            "instruction": "a natural hand",
            "idempotency_key": str(uuid4()),
        },
    )
    assert response.status_code == 202, response.text
    row = response.json()
    assert row["character_adapter"]["id"] == character["id"]
    assert row["character_adapter"]["weights_sha256"] == character["weights_sha256"]
    assert row["character_adapter"]["strength"] == 0.6
    assert row["style_adapter"]["id"] == style["id"]
    assert row["style_adapter"]["weights_sha256"] == style["weights_sha256"]
    assert row["style_adapter"]["strength"] == 0.4


async def test_repairs_refuse_foreign_characters_and_discarded_sources(studio):  # noqa: F811
    client, _, _, headers, base, *_ = studio
    url, source = await rendered(studio)
    asset = source["job"]["assets"][0]
    body = {
        "asset_id": asset["id"],
        "box": [400, 500, 560, 660],
        "instruction": "a natural hand",
        "idempotency_key": str(uuid4()),
    }
    foreign = await client.post(
        base + "/characters/other/looks/pose-repairs", headers=headers, json=body
    )
    assert foreign.status_code == 404
    discarded = await client.post(base + "/assets/" + asset["id"] + "/discard", headers=headers)
    assert discarded.status_code == 200, discarded.text
    refused = await client.post(url + "/pose-repairs", headers=headers, json=body)
    assert refused.status_code == 422, refused.text
