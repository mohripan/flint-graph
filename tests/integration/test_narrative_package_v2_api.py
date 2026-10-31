"""Saving story package v2 revisions: gate, upgrade, asset binding and NOTICES (ADR 0040)."""

import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import update
from test_narrative_asset_library_api import rgba_png, static_font, upload
from test_narrative_characters_api import MemoryStore, run_job

from flint_graph.api.dependencies import get_narrative_artifact_store
from flint_graph.application.narrative_image_workflow import ImageJobPayload
from flint_graph.application.services.narrative_package_v2 import NOTICE_MARKER
from flint_graph.application.services.narrative_release_execution import (
    ReleaseInputError,
    claim_release_execution,
    load_release_input,
)
from flint_graph.application.services.narrative_releases import BuildIdentity
from flint_graph.config import Settings, get_settings
from flint_graph.infrastructure.db.models import NarrativeAsset
from flint_graph.main import app
from flint_graph.narrative.package import attach_assets, load_text_package


def configure(**changes):
    base = app.dependency_overrides.get(get_settings, lambda: Settings(env="test"))()
    configured = base.model_copy(update=changes)
    app.dependency_overrides[get_settings] = lambda: configured


@pytest.fixture
async def v2(narrative_env, oidc_auth):
    client, factory, _ = narrative_env
    original = app.dependency_overrides.get(get_settings, lambda: Settings(env="test"))
    configure(narrative_package_v2_enabled=True, narrative_image_generation_enabled=True)
    store = MemoryStore()
    app.dependency_overrides[get_narrative_artifact_store] = lambda: store
    owner = {"Authorization": "Bearer " + oidc_auth("stage-owner")}
    try:
        workspace = (
            await client.post("/v1/workspaces", headers=owner, json={"name": "Stage"})
        ).json()
        headers = {**owner, "X-Tenant-ID": workspace["id"]}

        async def project(name="Harbor", schema="1"):
            # Upgrade flows start from a v1 project, which needs v2 off at creation.
            configure(narrative_package_v2_enabled=schema == "2")
            created = (
                await client.post(
                    "/v1/narrative/projects",
                    headers=headers,
                    json={"name": name, "idempotency_key": str(uuid4())},
                )
            ).json()
            configure(narrative_package_v2_enabled=True)
            return f"/v1/narrative/projects/{created['id']}", created

        yield client, factory, store, headers, project
    finally:
        app.dependency_overrides[get_settings] = original
        app.dependency_overrides.pop(get_narrative_artifact_store, None)


async def head(client, headers, base):
    project = (await client.get(base, headers=headers)).json()
    revision = (
        await client.get(f"{base}/revisions/{project['head_revision_id']}", headers=headers)
    ).json()
    return revision


async def upgrade(client, headers, base):
    current = await head(client, headers, base)
    return await client.post(
        f"{base}/upgrade",
        headers=headers,
        json={"base_revision_id": current["id"], "idempotency_key": str(uuid4())},
    )


async def save(client, headers, base, story, notices=""):
    current = await head(client, headers, base)
    return await client.post(
        f"{base}/revisions",
        headers=headers,
        json={
            "base_revision_id": current["id"],
            "idempotency_key": str(uuid4()),
            "story_json": json.dumps(story),
            "notices": notices,
        },
    )


@pytest.mark.anyio
async def test_new_projects_start_on_v2_unless_it_is_disabled(v2):
    client, _, _, headers, project = v2
    assert Settings(env="test").narrative_package_v2_enabled is True
    base, _ = await project(schema="2")
    revision = await head(client, headers, base)
    story = json.loads(revision["story_json"])
    assert story["schema_version"] == "2"
    package = load_text_package(revision["story_json"].encode())
    assert revision["content_hash"] == package.content_hash
    assert (await upgrade(client, headers, base)).status_code == 409
    old_base, _ = await project("Old")
    old = json.loads((await head(client, headers, old_base))["story_json"])
    assert old["schema_version"] == "1"


@pytest.mark.anyio
async def test_upgrade_is_explicit_gated_and_idempotent(v2):
    client, _, _, headers, project = v2
    base, _ = await project()
    configure(narrative_package_v2_enabled=False)
    refused = await upgrade(client, headers, base)
    assert refused.status_code == 409 and refused.json()["type"].endswith("package-v2-unavailable")
    configure(narrative_package_v2_enabled=True)
    v1 = await head(client, headers, base)
    key = str(uuid4())
    body = {"base_revision_id": v1["id"], "idempotency_key": key}
    upgraded = await client.post(f"{base}/upgrade", headers=headers, json=body)
    assert upgraded.status_code == 201, upgraded.text
    story = json.loads(upgraded.json()["story_json"])
    before = json.loads(v1["story_json"])
    assert story["schema_version"] == "2"
    assert {**story, "schema_version": "1"} == before, "Nothing else changes"
    replay = await client.post(f"{base}/upgrade", headers=headers, json=body)
    assert replay.status_code == 201 and replay.json()["id"] == upgraded.json()["id"]
    again = await upgrade(client, headers, base)
    assert again.status_code == 409


@pytest.mark.anyio
async def test_v2_saves_bind_approved_assets_and_server_builds_notices(v2):
    client, _, _, headers, project = v2
    base, _ = await project()
    background = (
        await upload(
            client,
            headers,
            base,
            kind="background",
            name="Dusk",
            data=rgba_png(),
            filename="d.png",
            media="image/png",
            form={
                "license": "CC BY 4.0",
                "notice": "Photo by A. Painter.",
                "rights_declared": "true",
            },
        )
    ).json()
    font = (
        await upload(
            client,
            headers,
            base,
            kind="font",
            name="Type",
            data=static_font(),
            filename="t.ttf",
            media="font/ttf",
            form={"license": "OFL-1.1", "notice": "", "rights_declared": "true"},
        )
    ).json()
    assert (await upgrade(client, headers, base)).status_code == 201
    story = json.loads((await head(client, headers, base))["story_json"])
    story["assets"] = {
        "dusk": {"kind": "image", "path": "assets/dusk.png", "sha256": background["sha256"]},
        "type": {"kind": "font", "path": "assets/type.ttf", "sha256": font["sha256"]},
    }
    story["theme"] = {"font": {"asset": "type", "size": 24}}
    entry = story["entry"]
    story["nodes"]["stage0"] = {"type": "stage", "background": "dusk", "next": entry}
    story["entry"] = "stage0"
    supplied = f"Story by me.\n\n{NOTICE_MARKER}\nforged section that must disappear\n"
    saved = await save(client, headers, base, story, supplied)
    assert saved.status_code == 201, saved.text
    revision = saved.json()
    notices = revision["notices"]
    assert notices.startswith("Story by me.\n\n" + NOTICE_MARKER + "\n")
    assert "forged" not in notices
    assert "dusk" in notices and "CC BY 4.0" in notices and "Photo by A. Painter." in notices
    assert "type" in notices and "OFL-1.1" in notices
    package = load_text_package(
        revision["story_json"].encode(), notices.encode(), allow_asset_refs=True
    )
    assert revision["content_hash"] == package.content_hash
    # Saving the same story again regenerates exactly the same section.
    again = await save(client, headers, base, story, notices)
    assert again.json()["notices"] == notices
    assert again.json()["content_hash"] == revision["content_hash"]
    # Discarding hides the asset from pickers but never breaks a binding.
    await client.post(f"{base}/assets/{background['id']}/discard", headers=headers)
    assert (await save(client, headers, base, story, "Story by me.")).status_code == 201


@pytest.mark.anyio
async def test_unknown_unapproved_foreign_and_mismatched_assets_are_refused(v2):
    client, factory, store, headers, project = v2
    base, _ = await project()
    other_base, _ = await project("Other")
    foreign = (
        await upload(
            client,
            headers,
            other_base,
            kind="background",
            name="Elsewhere",
            data=rgba_png(4, 4),
            filename="e.png",
            media="image/png",
        )
    ).json()
    mine = (
        await upload(
            client,
            headers,
            base,
            kind="background",
            name="Here",
            data=rgba_png(),
            filename="h.png",
            media="image/png",
        )
    ).json()
    job = await client.post(
        f"{base}/assets/background-jobs",
        headers=headers,
        json={"description": "sea", "count": 1, "idempotency_key": str(uuid4())},
    )
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=job.json()["id"]
    )
    await run_job(factory, store, payload)
    candidate = (await client.get(f"{base}/image-jobs/{job.json()['id']}", headers=headers)).json()[
        "assets"
    ][0]
    assert (await upgrade(client, headers, base)).status_code == 201
    story = json.loads((await head(client, headers, base))["story_json"])

    async def bind(kind, path, sha):
        value = json.loads(json.dumps(story))
        value["assets"] = {"art": {"kind": kind, "path": path, "sha256": sha}}
        return await save(client, headers, base, value)

    for sha in ("0" * 64, foreign["sha256"], candidate["sha256"]):
        refused = await bind("image", "assets/art.png", sha)
        assert refused.status_code == 422 and refused.json()["type"].endswith("unknown-asset")
    wrong = await bind("font", "assets/art.ttf", mine["sha256"])
    assert wrong.status_code == 422 and wrong.json()["type"].endswith("asset-kind")
    configure(narrative_package_v2_enabled=True, narrative_package_v2_asset_budget_bytes=10)
    over = await bind("image", "assets/art.png", mine["sha256"])
    assert over.status_code == 422 and over.json()["type"].endswith("asset-budget")


@pytest.mark.anyio
async def test_v2_is_gated_from_v1_bases_but_editing_v2_continues(v2):
    client, _, _, headers, project = v2
    base, _ = await project()
    v1_story = json.loads((await head(client, headers, base))["story_json"])
    configure(narrative_package_v2_enabled=False)
    refused = await save(client, headers, base, {**v1_story, "schema_version": "2"})
    assert refused.status_code == 409 and refused.json()["type"].endswith("package-v2-unavailable")
    configure(narrative_package_v2_enabled=True)
    assert (await upgrade(client, headers, base)).status_code == 201
    configure(narrative_package_v2_enabled=False)
    story = json.loads((await head(client, headers, base))["story_json"])
    story["title"] = "Harbor, revised"
    assert (await save(client, headers, base, story)).status_code == 201


async def bound_story(client, headers, base):
    """Upload a background and a font, upgrade, and save a v2 story that uses both."""
    background = (
        await upload(
            client,
            headers,
            base,
            kind="background",
            name="Dusk",
            data=rgba_png(),
            filename="d.png",
            media="image/png",
            form={
                "license": "CC BY 4.0",
                "notice": "Photo by A. Painter.",
                "rights_declared": "true",
            },
        )
    ).json()
    font = (
        await upload(
            client,
            headers,
            base,
            kind="font",
            name="Type",
            data=static_font(),
            filename="t.ttf",
            media="font/ttf",
            form={"license": "OFL-1.1", "notice": "", "rights_declared": "true"},
        )
    ).json()
    v1 = await head(client, headers, base)
    assert (await upgrade(client, headers, base)).status_code == 201
    story = json.loads((await head(client, headers, base))["story_json"])
    story["assets"] = {
        "dusk": {"kind": "image", "path": "assets/dusk.png", "sha256": background["sha256"]},
        "type": {"kind": "font", "path": "assets/type.ttf", "sha256": font["sha256"]},
    }
    story["theme"] = {"font": {"asset": "type"}}
    story["nodes"]["stage0"] = {"type": "stage", "background": "dusk", "next": story["entry"]}
    story["entry"] = "stage0"
    saved = await save(client, headers, base, story, "Story by me.")
    assert saved.status_code == 201, saved.text
    return saved.json(), v1, background, font


@pytest.mark.anyio
async def test_revision_assets_are_served_as_bound_even_after_discard(v2):
    client, _, _, headers, project = v2
    base, _ = await project()
    revision, v1, background, _ = await bound_story(client, headers, base)
    path = f"{base}/revisions/{revision['id']}/assets"
    image = await client.get(f"{path}/dusk", headers=headers)
    assert image.status_code == 200 and image.content == rgba_png()
    assert image.headers["content-type"] == "image/png"
    assert "immutable" in image.headers["cache-control"]
    assert image.headers["x-content-type-options"] == "nosniff"
    typed = await client.get(f"{path}/type", headers=headers)
    assert typed.status_code == 200 and typed.content == static_font()
    assert typed.headers["content-type"] == "font/ttf"
    await client.post(f"{base}/assets/{background['id']}/discard", headers=headers)
    assert (await client.get(f"{path}/dusk", headers=headers)).content == rgba_png()
    assert (await client.get(f"{path}/missing", headers=headers)).status_code == 404
    assert (await client.get(f"{path}/BAD", headers=headers)).status_code == 422
    old = f"{base}/revisions/{v1['id']}/assets/dusk"
    assert (await client.get(old, headers=headers)).status_code == 404
    other_base, _ = await project("Other")
    foreign = f"{other_base}/revisions/{revision['id']}/assets/dusk"
    assert (await client.get(foreign, headers=headers)).status_code == 404


@pytest.mark.anyio
async def test_v2_release_input_resolves_bound_assets_and_rechecks_notices(v2):
    client, factory, store, headers, project = v2
    base, _ = await project()
    revision, _, background, _ = await bound_story(client, headers, base)
    build = BuildIdentity("sha256:" + "a" * 64, "b" * 64)
    configure(
        narrative_package_v2_enabled=True,
        narrative_releases_enabled=True,
        narrative_release_builder_image_digest=build.builder_image_digest,
        narrative_release_toolchain_sha256=build.toolchain_sha256,
    )
    release = (
        await client.post(
            f"{base}/releases",
            headers=headers,
            json={"revision_id": revision["id"], "idempotency_key": str(uuid4())},
        )
    ).json()
    assert release["build_identity"]["runtime_version"] == "0.4.0"
    scope = {
        "tenant_id": UUID(headers["X-Tenant-ID"]),
        "release_id": UUID(release["id"]),
        "job_id": UUID(release["job"]["id"]),
    }
    token = uuid4()
    async with factory() as session:
        await claim_release_execution(session, **scope, token=token)
        await session.commit()
    async with factory() as session:
        loaded = await load_release_input(session, **scope, token=token, build=build)
        await session.commit()
    assert [source.id for source in loaded.assets] == ["dusk", "type"]
    assert all(source.object_key.endswith((".png", ".bin")) for source in loaded.assets)
    data = {
        source.id: await store.get_verified(
            source.object_key,
            expected_size=source.size,
            expected_sha256=source.sha256,
            max_bytes=source.max_bytes,
        )
        for source in loaded.assets
    }
    attached = attach_assets(loaded.package, data)
    assert attached.content_hash == release["package_hash"]
    # Asset rights are immutable; if a row ever drifted, the saved notices no longer
    # match what the server would build and the release refuses to ship.
    async with factory() as session:
        await session.execute(
            update(NarrativeAsset)
            .where(NarrativeAsset.id == UUID(background["id"]))
            .values(license="Changed")
        )
        await session.commit()
    async with factory() as session:
        with pytest.raises(ReleaseInputError, match=r"^input_integrity$"):
            await load_release_input(session, **scope, token=token, build=build)
