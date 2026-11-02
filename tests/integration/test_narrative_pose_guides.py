"""Versioned body guidance is explicit, frozen and separately pinned."""

from uuid import uuid4

import pytest
from test_narrative_characters_api import studio  # noqa: F401
from test_narrative_poses_api import admitted


async def test_pose_guides_require_explicit_operator_rollout(studio):  # noqa: F811
    client, _, _, headers, *_ = studio
    url, body, _ = await admitted(studio)
    response = await client.post(
        url + "/pose-jobs",
        headers=headers,
        json={**body, "pose_guide": "seated-front-v1", "idempotency_key": str(uuid4())},
    )
    assert response.status_code == 503, response.text
    assert response.json()["type"].endswith("pose-guide-unavailable")


@pytest.mark.parametrize(
    "guide_id", ["seated-front-v1", "standing-front-v1", "walking-three-quarter-v1"]
)
async def test_selected_body_guide_is_frozen_and_replay_survives_operator_changes(studio, guide_id):  # noqa: F811
    from flint_graph.config import get_settings
    from flint_graph.main import app

    client, _, _, headers, *_ = studio
    url, body, _ = await admitted(studio)
    settings = app.dependency_overrides[get_settings]().model_copy(
        update={
            "narrative_pose_guides_enabled": True,
            "narrative_pose_max_references": 2,
            "narrative_pose_control_manifest_sha256": "c" * 64,
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings
    capabilities = (await client.get(url + "/pose-jobs", headers=headers)).json()["capabilities"]
    guides = capabilities["body_guides"]
    assert [guide["id"] for guide in guides] == [
        "seated-front-v1",
        "standing-front-v1",
        "walking-three-quarter-v1",
    ]
    assert "arms relaxed" in guides[1]["suggested_pose"]
    assert "one foot forward" in guides[2]["suggested_pose"]
    body = {**body, "pose_guide": guide_id, "idempotency_key": str(uuid4())}
    response = await client.post(url + "/pose-jobs", headers=headers, json=body)
    assert response.status_code == 202, response.text
    row = response.json()
    assert "pose skeleton" in row["job"]["prompt"]
    assert row["pose_guide"]["id"] == guide_id
    assert row["pose_guide"]["control_manifest_sha256"] == "c" * 64
    assert len(row["pose_guide"]["points"]) == 18
    assert row["pose_guide"]["points"][10] != row["pose_guide"]["points"][13]
    settings = settings.model_copy(
        update={
            "narrative_pose_guides_enabled": False,
            "narrative_pose_control_manifest_sha256": "d" * 64,
        }
    )
    replay = await client.post(url + "/pose-jobs", headers=headers, json=body)
    assert replay.status_code == 202 and replay.json()["job"]["id"] == row["job"]["id"]
    assert replay.json()["pose_guide"] == row["pose_guide"]
    conflict = await client.post(
        url + "/pose-jobs", headers=headers, json={**body, "pose_guide": None}
    )
    assert conflict.status_code == 409


@pytest.mark.parametrize("pin", ["c", "d"])
async def test_worker_uses_the_frozen_body_guide_and_verifies_its_model_pin(studio, pin):  # noqa: F811
    from types import SimpleNamespace

    from test_narrative_characters_api import Dispatcher, FakeGenerator, environment

    from flint_graph.application.narrative_image_workflow import ImageJobPayload
    from flint_graph.application.services.narrative_image_relay import relay_image_batch
    from flint_graph.config import get_settings
    from flint_graph.infrastructure.narrative_imagegen import ModelIdentity
    from flint_graph.main import app
    from flint_graph.narrative.poses import MODEL_REPO, MODEL_REVISION
    from flint_graph.worker.activities.narrative_pose import NarrativePoseActivities

    client, factory, store, headers, *_ = studio
    url, body, previous = await admitted(studio)
    await client.post(
        studio[4] + "/image-jobs/" + previous["job"]["id"] + "/cancel", headers=headers
    )
    settings = app.dependency_overrides[get_settings]().model_copy(
        update={
            "narrative_pose_guides_enabled": True,
            "narrative_pose_max_references": 2,
            "narrative_pose_control_manifest_sha256": "c" * 64,
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings
    row = (
        await client.post(
            url + "/pose-jobs",
            headers=headers,
            json={**body, "pose_guide": "seated-front-v1", "idempotency_key": str(uuid4())},
        )
    ).json()
    dispatcher = Dispatcher()
    await relay_image_batch(factory, dispatcher=dispatcher, poses=True)
    generator = FakeGenerator()
    generator.model = ModelIdentity(MODEL_REPO, MODEL_REVISION, "apache-2.0")
    generator.model_manifest_sha256 = "b" * 64
    generator.cutout_manifest_sha256 = None
    generator.control_model = SimpleNamespace(manifest_sha256=pin * 64)
    activities = NarrativePoseActivities(factory=factory, generator=generator, store=store)
    data = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=row["job"]["id"]
    )
    outcome = await environment(data, dispatcher.run_id).run(activities.run, data)
    if pin == "d":
        assert outcome["status"] == "failed"
        assert not generator.requests
        return
    assert outcome["status"] == "completed"
    request = generator.requests[0]
    assert request.pose_guide.sha256 == row["pose_guide"]["sha256"]
    assert request.pose_guide.model_manifest_sha256 == "c" * 64
    assert request.additional_references == ()
    done = next(
        item
        for item in (await client.get(url + "/pose-jobs", headers=headers)).json()["jobs"]
        if item["job"]["id"] == row["job"]["id"]
    )
    runtime = done["job"]["assets"][0]["provenance"]["runtime"]
    assert runtime["pose_guide_sha256"] == row["pose_guide"]["sha256"]
    assert runtime["pose_control_applied"] == "true"
