"""Reference-conditioned character training is explicit and replayable."""

from uuid import uuid4

from test_narrative_character_adapters import look_request
from test_narrative_characters_api import studio  # noqa: F401

from flint_graph.config import get_settings
from flint_graph.main import app


async def test_reference_recipe_is_explicit_frozen_and_survives_rollout_changes(studio):  # noqa: F811
    client, _, _, headers, base, *_ = studio
    body, look = await look_request(studio)
    legacy = await client.post(base + "/style-jobs", headers=headers, json=body)
    assert legacy.status_code == 202
    assert legacy.json()["conditioning"] == "text"
    explicit_text = await client.post(
        base + "/style-jobs", headers=headers, json={**body, "conditioning": "text"}
    )
    assert explicit_text.status_code == 202
    assert explicit_text.json()["id"] == legacy.json()["id"]
    await client.post(base + "/style-jobs/" + legacy.json()["id"] + "/cancel", headers=headers)
    body = {**body, "conditioning": "reference", "idempotency_key": str(uuid4())}
    denied = await client.post(base + "/style-jobs", headers=headers, json=body)
    assert denied.status_code == 503
    configured = app.dependency_overrides[get_settings]().model_copy(
        update={"narrative_style_reference_training_enabled": True}
    )
    app.dependency_overrides[get_settings] = lambda: configured
    project_style = {k: v for k, v in body.items() if k != "character_look"}
    invalid = await client.post(base + "/style-jobs", headers=headers, json=project_style)
    assert invalid.status_code == 422
    assert invalid.json()["type"].endswith("invalid-training-conditioning")
    admitted = await client.post(base + "/style-jobs", headers=headers, json=body)
    assert admitted.status_code == 202, admitted.text
    row = admitted.json()
    assert row["conditioning"] == "reference"
    assert row["recipe_sha256"] != legacy.json()["recipe_sha256"]
    assert row["look"]["source_sha256"] == look["source_sha256"]
    configured = configured.model_copy(update={"narrative_style_reference_training_enabled": False})
    replay = await client.post(base + "/style-jobs", headers=headers, json=body)
    assert replay.status_code == 202 and replay.json()["id"] == row["id"]
    conflict = await client.post(
        base + "/style-jobs", headers=headers, json={**body, "conditioning": "text"}
    )
    assert conflict.status_code == 409
