"""Reviewed looks through the authenticated Studio API, independent of generation."""

import asyncio
from uuid import uuid4

import pytest
from test_narrative_characters_api import (  # noqa: F401 - shared fixture
    FakeGenerator,
    png,
    queue_job,
    run_job,
    studio,
)
from test_narrative_voice_references_api import add_member

from flint_graph.application.narrative_image_workflow import ImageJobPayload
from flint_graph.infrastructure.narrative_look_tagger import WD_MANIFEST


async def approved(client, headers, base, *, character="mira", shade=25):
    response = await client.post(
        base + "/assets",
        headers=headers,
        files={"file": ("look.png", png(80, 120, shade), "image/png")},
        data={
            "kind": "sprite",
            "name": "Travel coat",
            "license": "Original",
            "rights_declared": "true",
            "character_id": character,
        },
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


def look_body(asset, **changes):
    return {
        "name": "Travel coat",
        "asset_id": asset["id"],
        "identity_tags": ["white_hair", "red eyes"],
        "clothing_tags": ["navy coat", "red scarf"],
        "base_version": 0,
        "idempotency_key": str(uuid4()),
        **changes,
    }


async def test_lock_approved_look_persists_normalized_tags_and_replays_without_reselecting(studio):  # noqa: F811 - shared fixture
    client, _, _, headers, base, *_ = studio
    asset = await approved(client, headers, base)
    url = base + "/characters/mira/looks"
    body = look_body(asset)
    response = await client.post(url, headers=headers, json=body)
    assert response.status_code == 201, response.text
    look = response.json()
    assert look["identity_tags"] == ["white hair", "red eyes"]
    assert look["source_sha256"] == asset["sha256"]
    listed = (await client.get(url, headers=headers)).json()
    assert listed["selection"] == {"version": 1, "look_id": look["id"]}
    assert listed["looks"][0]["sha256"] == look["sha256"]
    cleared = await client.post(
        url + "/selection", headers=headers, json={"base_version": 1, "look_id": None}
    )
    assert cleared.status_code == 200, cleared.text
    replay = await client.post(url, headers=headers, json=body)
    assert replay.status_code == 201 and replay.json()["id"] == look["id"]
    listed = (await client.get(url, headers=headers)).json()
    assert listed["selection"] == {"version": 2, "look_id": None}


async def test_look_generations_pin_the_reviewed_description_and_retry_original_snapshot(studio):  # noqa: F811 - shared fixture
    client, factory, store, headers, base, *_ = studio
    asset = await approved(client, headers, base)
    url = base + "/characters/mira/looks"
    look = (await client.post(url, headers=headers, json=look_body(asset))).json()
    request = {
        "look_id": look["id"],
        "framing": "full_body",
        "count": 1,
        "transparent": False,
        "hires": False,
        "idempotency_key": str(uuid4()),
    }
    response = await client.post(url + "/portrait-jobs", headers=headers, json=request)
    assert response.status_code == 202, response.text
    first = response.json()
    assert "navy coat" in first["prompt"] and "red scarf" in first["prompt"]
    # A new outfit creates a new record and does not change the queued recipe.
    new = (
        await client.post(
            url,
            headers=headers,
            json=look_body(
                asset,
                name="Raincoat",
                clothing_tags=["yellow raincoat"],
                base_version=1,
                parent_look_id=look["id"],
            ),
        )
    ).json()
    replay = await client.post(url + "/portrait-jobs", headers=headers, json=request)
    assert replay.status_code == 202 and replay.json()["id"] == first["id"]
    wrong = await client.post(
        url + "/portrait-jobs", headers=headers, json={**request, "look_id": new["id"]}
    )
    assert wrong.status_code == 409
    history = (await client.get(url + "/jobs", headers=headers)).json()
    assert history["jobs"][0]["looks"][0]["sha256"] == look["sha256"]
    assert history["jobs"][0]["looks"][0]["clothing_tags"] == ["navy coat", "red scarf"]
    legacy_replay = await client.post(
        base + "/characters/mira/portrait-jobs",
        headers=headers,
        json={
            "appearance": "white hair, red eyes, navy coat, red scarf",
            "character_type": "other",
            "framing": "full_body",
            "count": 1,
            "idempotency_key": request["idempotency_key"],
            "transparent": False,
            "hires": False,
        },
    )
    assert legacy_replay.status_code == 409
    generator = FakeGenerator()
    await run_job(
        factory,
        store,
        ImageJobPayload(schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=first["id"]),
        generator,
    )
    assert generator.requests[0].prompt == first["prompt"]


async def test_expressions_and_cgs_use_the_locked_reference_and_words(studio):  # noqa: F811 - shared fixture
    client, _, _, headers, base, *_ = studio
    asset = await approved(client, headers, base)
    url = base + "/characters/mira/looks"
    look = (await client.post(url, headers=headers, json=look_body(asset))).json()
    expressions = await client.post(
        url + "/expression-jobs",
        headers=headers,
        json={
            "look_id": look["id"],
            "face_box": [10, 10, 60, 60],
            "expressions": ["happy"],
            "idempotency_key": str(uuid4()),
        },
    )
    assert expressions.status_code == 202, expressions.text
    assert expressions.json()["base_asset_id"] == asset["id"]
    assert "navy coat" in expressions.json()["prompt"]
    scene = await client.post(
        base + "/look-scene-art-jobs",
        headers=headers,
        json={
            "scene": "sitting in a garden",
            "characters": [{"character_id": "mira", "look_id": look["id"]}],
            "count": 1,
            "idempotency_key": str(uuid4()),
        },
    )
    assert scene.status_code == 202, scene.text
    assert scene.json()["reference_assets"][0]["asset_id"] == asset["id"]
    assert "navy coat" in scene.json()["prompt"] and "red scarf" in scene.json()["prompt"]


async def test_locked_generation_ignores_a_later_character_profile(studio):  # noqa: F811 - shared fixture
    client, _, _, headers, base, *_ = studio
    asset = await approved(client, headers, base)
    url = base + "/characters/mira/looks"
    look = (await client.post(url, headers=headers, json=look_body(asset))).json()
    # Profile writing is distinct from image admission. A later unusable recipe
    # must not replace, block or relabel an explicitly selected earlier look.
    saved = await client.put(
        base + "/characters/mira",
        headers=headers,
        json={
            "base_version": 0,
            "appearance": "nude body",
            "character_type": "woman",
            "framing": "portrait",
        },
    )
    assert saved.status_code == 200, saved.text
    expression = await client.post(
        url + "/expression-jobs",
        headers=headers,
        json={
            "look_id": look["id"],
            "face_box": [10, 10, 60, 60],
            "expressions": ["happy"],
            "idempotency_key": str(uuid4()),
        },
    )
    assert expression.status_code == 202, expression.text
    assert expression.json()["character_type"] == look["character_type"]
    assert expression.json()["appearance"] == "white hair, red eyes, navy coat, red scarf"
    scene = await client.post(
        base + "/look-scene-art-jobs",
        headers=headers,
        json={
            "characters": [{"character_id": "mira", "look_id": look["id"]}],
            "scene": "sitting in a garden",
            "count": 1,
            "idempotency_key": str(uuid4()),
        },
    )
    assert scene.status_code == 202, scene.text
    assert scene.json()["character_type"] == look["character_type"]
    assert "nude" not in scene.json()["prompt"] and "navy coat" in scene.json()["prompt"]


async def test_candidate_feedback_is_advisory_persistent_and_conflict_checked(studio):  # noqa: F811 - shared fixture
    client, _, _, headers, base, *_ = studio
    asset = await approved(client, headers, base)
    candidate = await approved(client, headers, base, shade=90)
    url = base + "/characters/mira/looks"
    look = (await client.post(url, headers=headers, json=look_body(asset))).json()
    review_url = url + f"/{look['id']}/reviews/{candidate['id']}"
    initial = await client.get(review_url, headers=headers)
    assert initial.status_code == 200, initial.text
    assert initial.json()["identity"] == "unknown" and initial.json()["version"] == 0
    body = {
        "base_version": 0,
        "identity": "same",
        "clothes": "drifted",
        "notes": "Coat buttons changed.",
    }
    response = await client.post(review_url, headers=headers, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 1
    assert (await client.post(review_url, headers=headers, json=body)).status_code == 409
    saved = (await client.get(review_url, headers=headers)).json()
    assert saved["clothes"] == "drifted" and saved["notes"] == body["notes"]
    # A warning never revokes approval or discards the creator's choice.
    assets = (await client.get(base + "/assets", headers=headers)).json()["assets"]
    assert next(a for a in assets if a["id"] == candidate["id"])["status"] == "approved"
    flags = (
        await client.get(
            base + "/look-reviews", headers=headers, params={"asset_id": candidate["id"]}
        )
    ).json()
    assert (
        flags["reviews"][0]["look_name"] == "Travel coat"
        and flags["reviews"][0]["clothes"] == "drifted"
    )


async def test_look_admission_keeps_geometry_expression_and_scene_guards(studio):  # noqa: F811 - shared fixture
    client, _, _, headers, base, *_ = studio
    asset = await approved(client, headers, base)
    url = base + "/characters/mira/looks"
    look = (await client.post(url, headers=headers, json=look_body(asset))).json()
    expression = {
        "look_id": look["id"],
        "face_box": [10, 10, 60, 60],
        "expressions": ["happy"],
        "idempotency_key": str(uuid4()),
    }
    for changes in (
        {"face_box": [10, 10, 90, 60]},  # outside the reference
        {"face_box": [10, 10, 20, 20]},  # too small to repaint
        {"face_box": [10, 10, 70, 30]},  # unusable aspect ratio
        {"expressions": ["happy!"]},  # invalid expression syntax
        {"expressions": ["happy", "happy"]},
    ):
        response = await client.post(
            url + "/expression-jobs", headers=headers, json={**expression, **changes}
        )
        assert response.status_code == 422, response.text
    scene = {
        "characters": [{"character_id": "mira", "look_id": look["id"]}],
        "scene": "sitting in a garden",
        "count": 1,
        "idempotency_key": str(uuid4()),
    }
    for changes in (
        {"characters": scene["characters"] * 2},
        {"characters": []},
        {"scene": "nude body"},
    ):
        response = await client.post(
            base + "/look-scene-art-jobs", headers=headers, json={**scene, **changes}
        )
        assert response.status_code == 422, response.text
    # Rejected requests have not spent admission capacity or created history.
    assert (await client.get(url + "/jobs", headers=headers)).json() == {"jobs": []}


async def test_tagger_suggestions_are_reviewed_before_they_become_a_locked_look(studio):  # noqa: F811 - shared fixture
    from flint_graph.api.routes.narrative_looks import get_look_tagger
    from flint_graph.main import app

    class Tagger:
        async def tag(self, data):
            assert data.startswith(b"\x89PNG")
            return {
                "model_manifest_sha256": WD_MANIFEST,
                "tagger_sha256": "a" * 64,
                "general_tags": {"white_hair": 0.9, "red_eyes": 0.8, "coat": 0.9, "1girl": 0.99},
                "rating_tags_never_prompt": {"general": 0.9},
            }

    client, _, _, headers, base, *_ = studio
    asset = await approved(client, headers, base)
    url = base + "/characters/mira/looks"
    app.dependency_overrides[get_look_tagger] = lambda: Tagger()
    try:
        response = await client.post(
            url + "/suggestions", headers=headers, json={"asset_id": asset["id"]}
        )
        assert response.status_code == 200, response.text
        suggested = response.json()
        assert suggested["identity_tags"] == ["white hair", "red eyes"]
        assert suggested["clothing_tags"] == ["coat"]
        # Creator edits the suggestion before locking it. No gender guess enters it.
        body = look_body(
            asset,
            identity_tags=["white hair", "amber eyes"],
            observation_id=suggested["observation_id"],
        )
        look = (await client.post(url, headers=headers, json=body)).json()
        assert look["identity_tags"] == ["white hair", "amber eyes"]
        assert look["tagger_observation"]["general_tags"]["red_eyes"] == 0.8
        assert "1girl" not in ", ".join(look["identity_tags"] + look["clothing_tags"])
    finally:
        app.dependency_overrides.pop(get_look_tagger, None)


async def test_look_roles_scope_policy_and_stale_selection(studio):  # noqa: F811 - shared fixture
    client, _, _, headers, base, workspace, oidc_auth = studio
    asset = await approved(client, headers, base)
    url = base + "/characters/mira/looks"
    look = (await client.post(url, headers=headers, json=look_body(asset))).json()
    await add_member(client, headers, workspace, "look-viewer", "viewer")
    viewer = {**headers, "Authorization": "Bearer " + oidc_auth("look-viewer")}
    assert (await client.get(url, headers=viewer)).status_code == 200
    assert (await client.post(url, headers=viewer, json=look_body(asset))).status_code == 403
    assert (
        await client.post(url + "/suggestions", headers=viewer, json={"asset_id": asset["id"]})
    ).status_code == 403
    stale = await client.post(
        url + "/selection", headers=headers, json={"look_id": None, "base_version": 0}
    )
    assert stale.status_code == 409
    blocked = await client.post(
        url, headers=headers, json=look_body(asset, identity_tags=["nude_body"], base_version=1)
    )
    assert blocked.status_code == 422
    other = await approved(client, headers, base, character="other", shade=72)
    assert (
        await client.post(url, headers=headers, json=look_body(other, base_version=1))
    ).status_code == 422
    another = (
        await client.post(
            "/v1/narrative/projects",
            headers=headers,
            json={"name": "Other", "idempotency_key": str(uuid4())},
        )
    ).json()
    other_url = f"/v1/narrative/projects/{another['id']}/characters/mira/looks"
    assert (await client.post(other_url, headers=headers, json=look_body(asset))).status_code == 404
    assert (
        await client.post(
            other_url + "/selection",
            headers=headers,
            json={"look_id": look["id"], "base_version": 0},
        )
    ).status_code == 404
    # An archived project cannot gain new reviewed looks or feedback.
    project = (await client.get(base, headers=headers)).json()
    assert (
        await client.post(
            base + "/archive",
            headers=headers,
            json={"base_revision_id": project["head_revision_id"], "archived": True},
        )
    ).status_code == 200
    assert (
        await client.post(url, headers=headers, json=look_body(asset, base_version=1))
    ).status_code == 409


async def test_clothing_comparison_does_not_invent_an_identity_or_an_approval_threshold(studio):  # noqa: F811 - shared fixture
    import hashlib

    from flint_graph.api.routes.narrative_looks import get_look_tagger
    from flint_graph.main import app

    client, _, _, headers, base, *_ = studio
    asset = await approved(client, headers, base)
    candidate = await approved(client, headers, base, shade=91)

    class Tagger:
        async def tag(self, data):
            ref = hashlib.sha256(data).hexdigest() == asset["sha256"]
            return {
                "model_manifest_sha256": WD_MANIFEST,
                "tagger_sha256": "a" * 64,
                "general_tags": {"coat": 1.0, "boots" if ref else "skirt": 1.0},
                "rating_tags_never_prompt": {},
            }

    url = base + "/characters/mira/looks"
    look = (await client.post(url, headers=headers, json=look_body(asset))).json()
    app.dependency_overrides[get_look_tagger] = lambda: Tagger()
    try:
        response = await client.post(
            url + f"/{look['id']}/compare/{candidate['id']}", headers=headers
        )
        assert response.status_code == 200, response.text
        assert abs(response.json()["clothing_overlap"] - 1 / 3) < 1e-9
        assert response.json()["identity"] is None and response.json()["automatic_verdict"] is None
        assert response.json()["reference_observation_id"]
    finally:
        app.dependency_overrides.pop(get_look_tagger, None)


async def test_two_members_retry_one_look_job_concurrently_on_postgres(studio, narrative_env):  # noqa: F811 - shared fixture
    if narrative_env[2] != "postgres":
        pytest.skip("PostgreSQL admission locks require the owned PG fixture")
    client, _, _, headers, base, workspace, oidc_auth = studio
    asset = await approved(client, headers, base)
    url = base + "/characters/mira/looks"
    look = (await client.post(url, headers=headers, json=look_body(asset))).json()
    await add_member(client, headers, workspace, "look-other", "member")
    other = {**headers, "Authorization": "Bearer " + oidc_auth("look-other")}
    body = {
        "look_id": look["id"],
        "framing": "full_body",
        "count": 1,
        "idempotency_key": str(uuid4()),
    }
    responses = await asyncio.gather(
        *(
            client.post(url + "/portrait-jobs", headers=actor, json=body)
            for actor in (headers, other)
        )
    )
    assert [response.status_code for response in responses] == [202, 202], [
        response.text for response in responses
    ]
    assert responses[0].json()["id"] == responses[1].json()["id"]
