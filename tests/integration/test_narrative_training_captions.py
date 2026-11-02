"""Training captions are scoped, optional proposals from the pinned CPU tagger."""

import hashlib
from uuid import uuid4

import pytest
from test_narrative_characters_api import studio  # noqa: F401
from test_narrative_looks_api import approved
from test_narrative_voice_references_api import add_member

from flint_graph.api.routes.narrative_looks import get_look_tagger
from flint_graph.infrastructure.narrative_look_tagger import WD_MANIFEST
from flint_graph.main import app


def observation(**changes):
    return {
        "model_manifest_sha256": WD_MANIFEST,
        "tagger_sha256": "a" * 64,
        "general_tags": {"white_hair": 0.9, "coat": 0.85, "standing": 0.8},
        "rating_tags_never_prompt": {"general": 0.99},
        **changes,
    }


async def test_caption_suggestion_uses_the_selected_image_without_starting_training(studio):  # noqa: F811
    client, _, _, headers, base, *_ = studio
    asset = await approved(client, headers, base)

    class Tagger:
        calls = 0

        async def tag(self, data):
            assert hashlib.sha256(data).hexdigest() == asset["sha256"]
            self.calls += 1
            if self.calls > 1:
                return observation(general_tags={"walking": 0.95})
            return {
                "model_manifest_sha256": WD_MANIFEST,
                "tagger_sha256": "a" * 64,
                "general_tags": {
                    "white_hair": 0.97,
                    "red_eyes": 0.93,
                    "blue_coat": 0.9,
                    "sitting": 0.88,
                    "chair": 0.85,
                    "1girl": 0.99,
                    "masterpiece": 0.99,
                    "long_hair": 0.1,
                    "rating:safe": 0.98,
                },
                "rating_tags_never_prompt": {"general": 0.99},
            }

    tagger = Tagger()
    app.dependency_overrides[get_look_tagger] = lambda: tagger
    try:
        url = base + "/style-jobs/caption-suggestions"
        result = await client.post(url, headers=headers, json={"asset_id": asset["id"]})
        assert result.status_code == 200, result.text
        row = result.json()
        assert row["caption"] == "white hair, red eyes, blue coat, sitting, chair"
        assert row["asset_id"] == asset["id"] and row["source_sha256"] == asset["sha256"]
        assert row["tags"][0] == {"tag": "white hair", "confidence": 0.97}
        assert row["model_manifest_sha256"] == WD_MANIFEST
        assert row["caption_version"] == "training-caption-v1"
        replay = await client.post(url, headers=headers, json={"asset_id": asset["id"]})
        assert replay.json()["observation_id"] == row["observation_id"]
        assert replay.json()["caption"] == row["caption"]
        assert replay.json()["tags"] == row["tags"]
        assert (await client.get(base + "/style-jobs", headers=headers)).json()["jobs"] == []
    finally:
        app.dependency_overrides.pop(get_look_tagger, None)


async def test_caption_permissions_source_scope_and_manual_fallback(studio):  # noqa: F811
    from flint_graph.infrastructure.narrative_look_tagger import unavailable

    client, _, _, headers, base, workspace, oidc_auth = studio
    asset = await approved(client, headers, base)
    calls = []

    class Tagger:
        async def tag(self, data):
            calls.append(data)
            raise unavailable()

    app.dependency_overrides[get_look_tagger] = lambda: Tagger()
    try:
        url = base + "/style-jobs/caption-suggestions"
        await add_member(client, headers, workspace, "caption-viewer", "viewer")
        viewer = {**headers, "Authorization": "Bearer " + oidc_auth("caption-viewer")}
        assert (
            await client.post(url, headers=viewer, json={"asset_id": asset["id"]})
        ).status_code == 403
        other = (
            await client.post(
                "/v1/narrative/projects",
                headers=headers,
                json={"name": "Other", "idempotency_key": str(uuid4())},
            )
        ).json()
        foreign = f"/v1/narrative/projects/{other['id']}/style-jobs/caption-suggestions"
        assert (
            await client.post(foreign, headers=headers, json={"asset_id": asset["id"]})
        ).status_code == 404
        assert not calls
        result = await client.post(url, headers=headers, json={"asset_id": asset["id"]})
        assert result.status_code == 503 and len(calls) == 1
        assert (
            await client.post(base + "/assets/" + asset["id"] + "/discard", headers=headers)
        ).status_code == 200
        assert (
            await client.post(url, headers=headers, json={"asset_id": asset["id"]})
        ).status_code == 422
        assert len(calls) == 1
        assert (await client.get(base + "/style-jobs", headers=headers)).json()["jobs"] == []
    finally:
        app.dependency_overrides.pop(get_look_tagger, None)


@pytest.mark.parametrize("change", ["discard", "archive"])
async def test_image_and_project_are_rechecked_after_tagging(studio, change):  # noqa: F811
    client, _, _, headers, base, *_ = studio
    asset = await approved(client, headers, base)

    class Tagger:
        async def tag(self, data):
            if change == "discard":
                changed = await client.post(
                    base + "/assets/" + asset["id"] + "/discard", headers=headers
                )
            else:
                project = (await client.get(base, headers=headers)).json()
                changed = await client.post(
                    base + "/archive",
                    headers=headers,
                    json={
                        "base_revision_id": project["head_revision_id"],
                        "archived": True,
                    },
                )
            assert changed.status_code == 200
            return observation()

    app.dependency_overrides[get_look_tagger] = lambda: Tagger()
    try:
        result = await client.post(
            base + "/style-jobs/caption-suggestions",
            headers=headers,
            json={"asset_id": asset["id"]},
        )
        assert result.status_code == (422 if change == "discard" else 409), result.text
    finally:
        app.dependency_overrides.pop(get_look_tagger, None)


async def test_caption_filter_keeps_manual_unknown_and_enforces_the_current_policy(
    studio,  # noqa: F811
    tmp_path,
):
    from flint_graph.config import get_settings

    client, _, _, headers, base, *_ = studio
    asset = await approved(client, headers, base)
    policy = tmp_path / "caption-policy.toml"
    policy.write_text('version = 1\nnegative = []\nblocked = ["coat"]\n')
    configured = app.dependency_overrides[get_settings]().model_copy(
        update={"narrative_image_content_policy": str(policy)}
    )
    app.dependency_overrides[get_settings] = lambda: configured

    class Tagger:
        async def tag(self, data):
            return observation(
                general_tags={"coat": 0.99, "1boy": 0.99, "monochrome": 0.99, "artist_coat": 0.99}
            )

    app.dependency_overrides[get_look_tagger] = lambda: Tagger()
    try:
        result = await client.post(
            base + "/style-jobs/caption-suggestions",
            headers=headers,
            json={"asset_id": asset["id"]},
        )
        assert result.status_code == 200, result.text
        assert result.json()["caption"] == "" and result.json()["tags"] == []
        assert result.json()["requires_review"] is True
    finally:
        app.dependency_overrides.pop(get_look_tagger, None)
