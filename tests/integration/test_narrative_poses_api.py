"""Pose generation is an image job pinned to a reviewed character look."""

from uuid import uuid4

from test_narrative_characters_api import (  # noqa: F401 - shared fixture
    Dispatcher,
    FakeGenerator,
    environment,
    studio,
)
from test_narrative_looks_api import approved, look_body

from flint_graph.application.narrative_image_workflow import ImageJobPayload
from flint_graph.application.services.narrative_image_relay import relay_image_batch
from flint_graph.config import get_settings
from flint_graph.infrastructure.narrative_imagegen import ModelIdentity
from flint_graph.main import app
from flint_graph.narrative.poses import MODEL_REPO, MODEL_REVISION


async def test_pose_job_freezes_the_look_instruction_and_model_pin(studio):  # noqa: F811
    client, _, _, headers, base, *_ = studio
    original = app.dependency_overrides[get_settings]
    settings = original().model_copy(
        update={
            "narrative_pose_generation_enabled": True,
            "narrative_pose_model_manifest_sha256": "b" * 64,
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings
    asset = await approved(client, headers, base)
    url = base + "/characters/mira/looks"
    look = (await client.post(url, headers=headers, json=look_body(asset))).json()
    body = {
        "look_id": look["id"],
        "pose": "sitting on a chair, hands resting in lap",
        "count": 1,
        "transparent": False,
        "idempotency_key": str(uuid4()),
    }
    response = await client.post(url + "/pose-jobs", headers=headers, json=body)
    assert response.status_code == 202, response.text
    result = response.json()
    assert result["operation"] == "pose"
    assert result["look"]["sha256"] == look["sha256"]
    assert result["model_manifest_sha256"] == "b" * 64
    assert "navy coat" in result["job"]["prompt"]
    assert "hands resting in lap" in result["job"]["prompt"]
    assert result["job"]["steps"] == 4 and result["job"]["guidance"] == 1
    replay = await client.post(url + "/pose-jobs", headers=headers, json=body)
    assert replay.status_code == 202 and replay.json()["job"]["id"] == result["job"]["id"]
    changed = await client.post(
        url + "/pose-jobs", headers=headers, json={**body, "pose": "standing"}
    )
    assert changed.status_code == 409
    # Ordinary image workers must never send these jobs to Animagine.
    factory = studio[1]
    ordinary, poses = Dispatcher(), Dispatcher()
    assert await relay_image_batch(factory, dispatcher=ordinary) == 0
    assert ordinary.started == []
    assert await relay_image_batch(factory, dispatcher=poses, poses=True) == 1
    assert poses.started[0]["job_id"] == result["job"]["id"]
    from flint_graph.worker.activities.narrative_pose import NarrativePoseActivities

    generator = FakeGenerator()
    generator.model = ModelIdentity(MODEL_REPO, MODEL_REVISION, "apache-2.0")
    generator.model_manifest_sha256 = "b" * 64
    generator.cutout_manifest_sha256 = None
    activity = NarrativePoseActivities(factory=factory, generator=generator, store=studio[2])
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=result["job"]["id"]
    )
    outcome = await environment(payload, poses.run_id).run(activity.run, payload)
    assert outcome["status"] == "completed"
    assert generator.requests[0].reference.startswith(b"\x89PNG")
    history = await client.get(url + "/pose-jobs", headers=headers)
    assert history.status_code == 200
    assert history.json()["jobs"][0]["job"]["status"] == "completed"
    assert len(history.json()["jobs"][0]["job"]["assets"]) == 1
    assert history.json()["capabilities"]["available"] is True
    invalid = await client.post(
        url + "/pose-jobs",
        headers=headers,
        json={**body, "pose": "sitting\u0001", "idempotency_key": str(uuid4())},
    )
    assert invalid.status_code == 422


async def admitted(studio):  # noqa: F811 - shared fixture
    client, _, _, headers, base, *_ = studio
    configured = app.dependency_overrides[get_settings]().model_copy(
        update={
            "narrative_pose_generation_enabled": True,
            "narrative_pose_model_manifest_sha256": "b" * 64,
        }
    )
    app.dependency_overrides[get_settings] = lambda: configured
    asset = await approved(client, headers, base)
    url = base + "/characters/mira/looks"
    look = (await client.post(url, headers=headers, json=look_body(asset))).json()
    body = dict(
        look_id=look["id"],
        pose="standing, arms relaxed",
        count=1,
        transparent=False,
        idempotency_key=str(uuid4()),
    )
    result = await client.post(url + "/pose-jobs", headers=headers, json=body)
    assert result.status_code == 202
    return url, body, result.json()


async def test_cancel_and_recovery_are_routed_only_to_pose_runs(studio):  # noqa: F811
    import asyncio
    from datetime import timedelta

    from flint_graph.application.services.narrative_image_relay import recover_stale_image_jobs
    from flint_graph.worker.activities.narrative_pose import NarrativePoseActivities

    client, factory, store, headers, base, *_ = studio
    url, body, pose = await admitted(studio)
    ordinary, poses = Dispatcher(closed=True), Dispatcher(closed=True)
    assert await relay_image_batch(factory, dispatcher=poses, poses=True) == 1
    began, resume = asyncio.Event(), asyncio.Event()

    class Paused(FakeGenerator):
        async def generate(self, request, *, on_progress):
            began.set()
            await resume.wait()
            return await super().generate(request, on_progress=on_progress)

    generator = Paused()
    generator.model = ModelIdentity(MODEL_REPO, MODEL_REVISION, "apache-2.0")
    generator.model_manifest_sha256 = "b" * 64
    activity = NarrativePoseActivities(factory=factory, generator=generator, store=store)
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=pose["job"]["id"]
    )
    running = asyncio.create_task(environment(payload, poses.run_id).run(activity.run, payload))
    await asyncio.wait_for(began.wait(), 5)
    try:
        response = await client.post(
            base + "/image-jobs/" + pose["job"]["id"] + "/cancel", headers=headers
        )
        assert response.status_code == 200
        assert await relay_image_batch(factory, dispatcher=ordinary) == 0
        assert await relay_image_batch(factory, dispatcher=poses, poses=True) == 1
        assert len(poses.cancelled) == 1
    finally:
        resume.set()
        await running
    job = (await client.get(base + "/image-jobs/" + pose["job"]["id"], headers=headers)).json()
    assert job["status"] == "cancelled" and job["assets"] == []
    response = await client.post(
        url + "/pose-jobs", headers=headers, json={**body, "idempotency_key": str(uuid4())}
    )
    assert response.status_code == 202
    await relay_image_batch(factory, dispatcher=poses, poses=True)
    assert (
        await recover_stale_image_jobs(factory, dispatcher=ordinary, older_than=timedelta(0)) == 0
    )
    assert (
        await recover_stale_image_jobs(
            factory, dispatcher=poses, poses=True, older_than=timedelta(0)
        )
        == 1
    )


async def test_changed_model_pin_cannot_publish_a_pose(studio):  # noqa: F811
    from flint_graph.worker.activities.narrative_pose import NarrativePoseActivities

    client, factory, store, headers, base, *_ = studio
    _, _, result = await admitted(studio)
    dispatcher = Dispatcher()
    await relay_image_batch(factory, dispatcher=dispatcher, poses=True)
    generator = FakeGenerator()
    generator.model = ModelIdentity(MODEL_REPO, MODEL_REVISION, "apache-2.0")
    generator.model_manifest_sha256 = "c" * 64
    activity = NarrativePoseActivities(factory=factory, generator=generator, store=store)
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=result["job"]["id"]
    )
    outcome = await environment(payload, dispatcher.run_id).run(activity.run, payload)
    assert outcome["status"] == "failed"
    job = (await client.get(base + "/image-jobs/" + payload["job_id"], headers=headers)).json()
    assert job["error_code"] == "model_pin_mismatch" and job["assets"] == []
    assert generator.requests == []


async def test_pose_access_policy_and_archiving_match_image_jobs(studio):  # noqa: F811
    from test_narrative_voice_references_api import add_member

    client, _, _, headers, base, workspace, oidc_auth = studio
    url, body, _ = await admitted(studio)
    await add_member(client, headers, workspace, "pose-viewer", "viewer")
    viewer = {**headers, "Authorization": "Bearer " + oidc_auth("pose-viewer")}
    assert (await client.get(url + "/pose-jobs", headers=viewer)).status_code == 200
    assert (await client.post(url + "/pose-jobs", headers=viewer, json=body)).status_code == 403
    foreign = (
        await client.post(
            "/v1/workspaces",
            headers={"Authorization": headers["Authorization"]},
            json={"name": "Other pose workspace"},
        )
    ).json()
    other = {**headers, "X-Tenant-ID": foreign["id"]}
    assert (await client.get(url + "/pose-jobs", headers=other)).status_code == 404
    assert (await client.post(url + "/pose-jobs", headers=other, json=body)).status_code == 404
    blocked = await client.post(
        url + "/pose-jobs",
        headers=headers,
        json={**body, "pose": "nude body", "idempotency_key": str(uuid4())},
    )
    assert blocked.status_code == 422
    project = (await client.get(base, headers=headers)).json()
    assert (
        await client.post(
            base + "/archive",
            headers=headers,
            json={"base_revision_id": project["head_revision_id"], "archived": True},
        )
    ).status_code == 200
    assert (
        await client.post(
            url + "/pose-jobs", headers=headers, json={**body, "idempotency_key": str(uuid4())}
        )
    ).status_code == 409


async def test_two_approved_views_are_frozen_and_used_in_order(studio):  # noqa: F811
    from flint_graph.worker.activities.narrative_pose import NarrativePoseActivities

    client, factory, store, headers, base, *_ = studio
    url, body, _ = await admitted(studio)
    config = app.dependency_overrides[get_settings]().model_copy(
        update={"narrative_pose_max_references": 2}
    )
    app.dependency_overrides[get_settings] = lambda: config
    extra = await approved(client, headers, base, shade=89)
    body = {
        **body,
        "additional_references": [{"asset_id": extra["id"], "view": "back"}],
        "idempotency_key": str(uuid4()),
    }
    response = await client.post(url + "/pose-jobs", headers=headers, json=body)
    assert response.status_code == 202, response.text
    result = response.json()
    assert [item["view"] for item in result["references"]] == ["primary", "back"]
    assert result["references"][1]["sha256"] == extra["sha256"]
    assert "same character" in result["job"]["prompt"].lower()
    assert "back" in result["job"]["prompt"].lower()
    assert "do not blend" in result["job"]["prompt"].lower()
    replay = await client.post(url + "/pose-jobs", headers=headers, json=body)
    assert replay.json()["job"]["id"] == result["job"]["id"]
    changed = await client.post(
        url + "/pose-jobs",
        headers=headers,
        json={**body, "additional_references": [{"asset_id": extra["id"], "view": "side"}]},
    )
    assert changed.status_code == 409
    # Consume both accepted jobs; the new one must get two verified source images.
    dispatcher = Dispatcher()
    await relay_image_batch(factory, dispatcher=dispatcher, poses=True)
    generator = FakeGenerator()
    generator.model = ModelIdentity(MODEL_REPO, MODEL_REVISION, "apache-2.0")
    generator.model_manifest_sha256 = "b" * 64
    activity = NarrativePoseActivities(factory=factory, generator=generator, store=store)
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=result["job"]["id"]
    )
    outcome = await environment(payload, dispatcher.run_id).run(activity.run, payload)
    assert outcome["status"] == "completed"
    assert len(generator.requests[0].additional_references) == 1
    assert generator.requests[0].additional_references[0] != generator.requests[0].reference
    history = (await client.get(url + "/pose-jobs", headers=headers)).json()
    assert history["capabilities"]["max_references"] == 2
    assert (
        next(item for item in history["jobs"] if item["job"]["id"] == result["job"]["id"])[
            "references"
        ]
        == result["references"]
    )


async def test_pose_prompt_preserves_primary_rendering_and_gives_extra_views_only_geometry(studio):  # noqa: F811
    _, _, result = await admitted(studio)
    prompt = result["job"]["prompt"].lower()
    assert "line weight" in prompt and "light direction" in prompt
    assert "shading" in prompt and "palette" in prompt


async def test_additional_view_rejects_unapproved_foreign_and_duplicate_images(studio):  # noqa: F811
    client, _, _, headers, base, *_ = studio
    url, body, result = await admitted(studio)
    config = app.dependency_overrides[get_settings]().model_copy(
        update={"narrative_pose_max_references": 2}
    )
    app.dependency_overrides[get_settings] = lambda: config
    duplicate = result["look"]["asset_id"]
    foreign = await approved(client, headers, base, character="someone_else", shade=91)
    for asset_id, status in [(duplicate, 422), (foreign["id"], 422), (str(uuid4()), 404)]:
        response = await client.post(
            url + "/pose-jobs",
            headers=headers,
            json={
                **body,
                "idempotency_key": str(uuid4()),
                "additional_references": [{"asset_id": asset_id, "view": "detail"}],
            },
        )
        assert response.status_code == status, response.text
    replay = await client.post(
        url + "/pose-jobs", headers=headers, json={**body, "additional_references": []}
    )
    assert replay.status_code == 202 and replay.json()["job"]["id"] == result["job"]["id"]


async def test_legacy_single_reference_jobs_still_execute_without_new_reference_rows(studio):  # noqa: F811
    from uuid import UUID

    from sqlalchemy import delete

    from flint_graph.infrastructure.db.narrative_pose_models import NarrativePoseReference
    from flint_graph.worker.activities.narrative_pose import NarrativePoseActivities

    client, factory, store, headers, base, *_ = studio
    url, body, result = await admitted(studio)
    async with factory() as session:
        await session.execute(
            delete(NarrativePoseReference).where(
                NarrativePoseReference.job_id == UUID(result["job"]["id"])
            )
        )
        await session.commit()
    replay = await client.post(url + "/pose-jobs", headers=headers, json=body)
    assert replay.status_code == 202 and len(replay.json()["references"]) == 1
    dispatcher = Dispatcher()
    await relay_image_batch(factory, dispatcher=dispatcher, poses=True)
    gen = FakeGenerator()
    gen.model = ModelIdentity(MODEL_REPO, MODEL_REVISION, "apache-2.0")
    gen.model_manifest_sha256 = "b" * 64
    activity = NarrativePoseActivities(factory=factory, generator=gen, store=store)
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=result["job"]["id"]
    )
    outcome = await environment(payload, dispatcher.run_id).run(activity.run, payload)
    assert outcome["status"] == "completed" and gen.requests[0].additional_references == ()
    job = (await client.get(base + "/image-jobs/" + result["job"]["id"], headers=headers)).json()
    assert job["assets"][0]["provenance"]["runtime"]["reference_count"] == "1"
    assert job["assets"][0]["provenance"]["runtime"]["references_sha256"] != (
        "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
    )
