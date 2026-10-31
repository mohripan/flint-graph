"""Project asset library: uploads with rights metadata, kinds and backgrounds (ADR 0040)."""

import hashlib
import struct
import zlib
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from test_narrative_characters_api import (  # noqa: F401 - shared fixture and fakes
    FakeGenerator,
    job_row,
    run_job,
    studio,
)

from flint_graph.application.narrative_image_workflow import ImageJobPayload
from flint_graph.infrastructure.db.models import NarrativeAsset

VARIABLE_FONT = (Path(__file__).parents[2] / "runtimes/godot/fonts/Lora.ttf").read_bytes()
DECLARED = {"license": "Own work", "notice": "Drawn by the creator.", "rights_declared": "true"}


def rgba_png(width=12, height=20):
    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    row = b"\x00" + bytes([200, 80, 40, 255, 0, 0, 0, 0]) * (width // 2)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def static_font(fs_type=0):
    tables = {tag: b"x" * 8 for tag in (b"cmap", b"glyf", b"head", b"loca", b"name")}
    tables[b"OS/2"] = b"\x00" * 8 + struct.pack(">H", fs_type) + b"\x00" * 6
    header = b"\x00\x01\x00\x00" + struct.pack(">HHHH", len(tables), 16, 4, 0)
    offset, directory, body = 12 + 16 * len(tables), b"", b""
    for tag in sorted(tables):
        directory += tag + struct.pack(">III", 0, offset + len(body), len(tables[tag]))
        body += tables[tag]
    return header + directory + body


FONT = static_font()


async def upload(client, headers, base, *, kind, name, data, filename, media, form=None):
    return await client.post(
        f"{base}/assets",
        headers=headers,
        data={"kind": kind, "name": name, **(DECLARED if form is None else form)},
        files={"file": (filename, data, media)},
    )


@pytest.mark.anyio
async def test_png_and_font_uploads_store_verified_bytes_with_rights_metadata(studio):  # noqa: F811
    client, _, store, headers, base, *_ = studio
    sprite = await upload(
        client,
        headers,
        base,
        kind="sprite",
        name="Mira (neutral)",
        data=rgba_png(),
        filename="mira.png",
        media="image/png",
    )
    assert sprite.status_code == 201, sprite.text
    body = sprite.json()
    assert (body["kind"], body["status"], body["source"], body["media_type"]) == (
        "sprite",
        "approved",
        "uploaded",
        "image/png",
    )
    assert (body["name"], body["width"], body["height"]) == ("Mira (neutral)", 12, 20)
    assert (body["license"], body["notice"]) == ("Own work", "Drawn by the creator.")
    assert body["rights_declared_at"] and body["approved_at"]
    image = await client.get(f"{base}/assets/{body['id']}/content", headers=headers)
    assert image.status_code == 200 and image.content == rgba_png()
    thumb = await client.get(
        f"{base}/assets/{body['id']}/content?variant=thumbnail", headers=headers
    )
    assert thumb.content == rgba_png(), "Uploads have no separate thumbnail yet"

    font = await upload(
        client,
        headers,
        base,
        kind="font",
        name="Plain",
        data=FONT,
        filename="Plain.ttf",
        media="font/ttf",
        form={**DECLARED, "license": "OFL-1.1"},
    )
    assert font.status_code == 201, font.text
    font_body = font.json()
    assert (font_body["kind"], font_body["media_type"], font_body["width"]) == (
        "font",
        "font/ttf",
        None,
    )
    assert font_body["sha256"] == hashlib.sha256(FONT).hexdigest()
    served = await client.get(f"{base}/assets/{font_body['id']}/content", headers=headers)
    assert served.headers["content-type"] == "font/ttf" and served.content == FONT
    no_thumb = await client.get(
        f"{base}/assets/{font_body['id']}/content?variant=thumbnail", headers=headers
    )
    assert no_thumb.status_code == 404
    assert len(store.objects) == 2


@pytest.mark.anyio
async def test_editor_metadata_is_stripped_and_identical_files_are_not_duplicated(studio):  # noqa: F811
    client, _, store, headers, base, *_ = studio
    clean = rgba_png()
    text = b"tEXt" + b"Software\x00GIMP 2.10"
    metadata = struct.pack(">I", len(text) - 4) + text + struct.pack(">I", zlib.crc32(text))
    gimp = clean[:33] + metadata + clean[33:]
    first = await upload(
        client,
        headers,
        base,
        kind="sprite",
        name="From GIMP",
        data=gimp,
        filename="g.png",
        media="image/png",
    )
    assert first.status_code == 201, first.text
    assert first.json()["sha256"] == hashlib.sha256(clean).hexdigest(), "Stored without metadata"
    again = await upload(
        client,
        headers,
        base,
        kind="sprite",
        name="Again",
        data=clean,
        filename="g.png",
        media="image/png",
    )
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
    other_kind = await upload(
        client,
        headers,
        base,
        kind="background",
        name="Again",
        data=clean,
        filename="g.png",
        media="image/png",
    )
    assert other_kind.status_code == 409
    await client.post(f"{base}/assets/{first.json()['id']}/discard", headers=headers)
    fresh = await upload(
        client,
        headers,
        base,
        kind="background",
        name="New",
        data=clean,
        filename="g.png",
        media="image/png",
    )
    assert fresh.status_code == 201 and fresh.json()["id"] != first.json()["id"]
    assert len(store.objects) == 2


@pytest.mark.anyio
async def test_invalid_uploads_are_rejected_before_anything_is_stored(studio):  # noqa: F811
    client, factory, store, headers, base, *_ = studio
    cases = [
        ("sprite", rgba_png()[:-6], "image/png", DECLARED),
        ("font", rgba_png(), "font/ttf", DECLARED),
        ("background", static_font(), "image/png", DECLARED),
        ("sprite", rgba_png(), "image/png", {**DECLARED, "rights_declared": "false"}),
        ("sprite", rgba_png(), "image/png", {**DECLARED, "license": ""}),
        ("character_portrait", rgba_png(), "image/png", DECLARED),
        ("music", rgba_png(), "image/png", DECLARED),
        ("font", static_font(fs_type=0x0002), "font/ttf", DECLARED),
        ("font", VARIABLE_FONT, "font/ttf", DECLARED),
    ]
    for kind, data, media, form in cases:
        response = await upload(
            client,
            headers,
            base,
            kind=kind,
            name="Bad",
            data=data,
            filename="x",
            media=media,
            form=form,
        )
        assert response.status_code == 422, (kind, response.status_code, response.text)
    unnamed = await upload(
        client,
        headers,
        base,
        kind="sprite",
        name="",
        data=rgba_png(),
        filename="x",
        media="image/png",
    )
    assert unnamed.status_code == 422
    huge = await upload(
        client,
        headers,
        base,
        kind="image",
        name="Huge",
        data=b"\x89PNG" + b"0" * (11 << 20),
        filename="huge.png",
        media="image/png",
    )
    assert huge.status_code == 413
    async with factory() as session:
        assert list(await session.scalars(select(NarrativeAsset))) == []
    assert store.objects == {}


@pytest.mark.anyio
async def test_library_lists_filters_renames_and_approves(studio):  # noqa: F811
    client, factory, store, headers, base, *_ = studio
    ids = []
    for index in range(3):
        response = await upload(
            client,
            headers,
            base,
            kind="background" if index else "sprite",
            name=f"Art {index}",
            data=rgba_png(width=2 * (index + 1)),
            filename="art.png",
            media="image/png",
        )
        ids.append(response.json()["id"])
    listed = (await client.get(f"{base}/assets", headers=headers)).json()
    assert [item["id"] for item in listed["assets"]] == ids[::-1], "Newest first"
    backgrounds = (await client.get(f"{base}/assets?kind=background", headers=headers)).json()
    assert [item["id"] for item in backgrounds["assets"]] == [ids[2], ids[1]]
    page = (await client.get(f"{base}/assets?limit=2", headers=headers)).json()
    assert [item["id"] for item in page["assets"]] == [ids[2], ids[1]]
    rest = (
        await client.get(f"{base}/assets?limit=2&before={page['next_before']}", headers=headers)
    ).json()
    assert [item["id"] for item in rest["assets"]] == [ids[0]] and rest["next_before"] is None
    renamed = await client.patch(
        f"{base}/assets/{ids[0]}", headers=headers, json={"name": "  Mira neutral  "}
    )
    assert renamed.status_code == 200 and renamed.json()["name"] == "Mira neutral"
    assert (
        await client.patch(f"{base}/assets/{ids[0]}", headers=headers, json={"name": " "})
    ).status_code == 422

    job = await client.post(
        f"{base}/assets/background-jobs",
        headers=headers,
        json={"description": "harbor at dusk", "count": 1, "idempotency_key": str(uuid4())},
    )
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=job.json()["id"]
    )
    await run_job(factory, store, payload)
    [candidate] = (await client.get(f"{base}/assets?status=candidate", headers=headers)).json()[
        "assets"
    ]
    approved = await client.post(f"{base}/assets/{candidate['id']}/approve", headers=headers)
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    again = await client.post(f"{base}/assets/{candidate['id']}/approve", headers=headers)
    assert (
        again.status_code == 200 and again.json()["approved_at"] == approved.json()["approved_at"]
    )


@pytest.mark.anyio
async def test_background_jobs_render_landscape_scenery_candidates(studio):  # noqa: F811
    client, factory, store, headers, base, *_ = studio
    response = await client.post(
        f"{base}/assets/background-jobs",
        headers=headers,
        json={
            "description": "lighthouse at dusk, fog",
            "count": 2,
            "idempotency_key": str(uuid4()),
        },
    )
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["purpose"] == "background" and job["character_id"] is None
    assert (job["width"], job["height"]) == (1344, 768)
    assert job["prompt"].startswith("no humans, scenery, lighthouse at dusk, fog")
    assert "1girl" in job["negative_prompt"]
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=job["id"]
    )
    generator = FakeGenerator()
    assert (await run_job(factory, store, payload, generator))["status"] == "completed"
    assert (generator.requests[0].width, generator.requests[0].height) == (1344, 768)
    assert (await job_row(factory, payload)).status == "completed"
    async with factory() as session:
        assets = list(
            await session.scalars(
                select(NarrativeAsset).where(NarrativeAsset.job_id == UUID(job["id"]))
            )
        )
    assert {asset.kind for asset in assets} == {"background"}
    assert [asset.name for asset in sorted(assets, key=lambda item: item.job_index)] == [
        "lighthouse at dusk, fog 1",
        "lighthouse at dusk, fog 2",
    ]
    jobs = (await client.get(f"{base}/assets/background-jobs", headers=headers)).json()["jobs"]
    assert [item["id"] for item in jobs] == [job["id"]] and len(jobs[0]["assets"]) == 2
    for bad in [{"description": ""}, {"description": "x" * 601}, {"count": 5}]:
        body = {"description": "sea", "count": 1, "idempotency_key": str(uuid4()), **bad}
        assert (
            await client.post(f"{base}/assets/background-jobs", headers=headers, json=body)
        ).status_code == 422
    listed = (await client.get(f"{base}/assets?kind=background", headers=headers)).json()
    assert [item["name"] for item in listed["assets"]] == [
        "lighthouse at dusk, fog 1",
        "lighthouse at dusk, fog 2",
    ], "One job's candidates read in generation order even with equal clock readings"
    long = await client.post(
        f"{base}/assets/background-jobs",
        headers=headers,
        json={
            "description": "old fishing harbor at dusk, fog over the water, lanterns on a "
            "wooden pier, lighthouse in the distance",
            "count": 1,
            "idempotency_key": str(uuid4()),
        },
    )
    long_payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=long.json()["id"]
    )
    await run_job(factory, store, long_payload)
    async with factory() as session:
        named = await session.scalar(
            select(NarrativeAsset.name).where(NarrativeAsset.job_id == UUID(long.json()["id"]))
        )
    assert named == "old fishing harbor at dusk, fog over the water, lanterns on… 1"


class Repeating(FakeGenerator):
    """Returns the same bytes for every image, as a fixed seed and prompt would."""

    async def generate(self, request, *, on_progress):
        result = await super().generate(request, on_progress=on_progress)
        return replace(
            result,
            images=tuple(
                replace(image, index=index, seed=request.seeds[index])
                for index, image in enumerate([result.images[0]] * len(result.images))
            ),
        )


@pytest.mark.anyio
async def test_identical_generated_images_become_one_asset(studio):  # noqa: F811
    client, factory, store, headers, base, *_ = studio
    job = await client.post(
        f"{base}/assets/background-jobs",
        headers=headers,
        json={"description": "quiet bay", "count": 3, "idempotency_key": str(uuid4())},
    )
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=job.json()["id"]
    )
    assert (await run_job(factory, store, payload, Repeating()))["status"] == "completed"
    done = (await client.get(f"{base}/image-jobs/{job.json()['id']}", headers=headers)).json()
    assert len(done["assets"]) == 1 and done["progress"] == 3


@pytest.mark.anyio
async def test_viewers_read_members_upload_and_archived_projects_refuse(studio):  # noqa: F811
    client, _, _, headers, base, workspace, oidc_auth = studio
    added = await client.post(
        f"/v1/workspaces/{workspace['id']}/members",
        headers=headers,
        json={
            "oidc_issuer": "https://keycloak.example/realms/flintgraph",
            "oidc_subject": "library-viewer",
            "role": "viewer",
        },
    )
    assert added.status_code == 201
    viewer = {**headers, "Authorization": "Bearer " + oidc_auth("library-viewer")}
    assert (await client.get(f"{base}/assets", headers=viewer)).status_code == 200
    denied = await upload(
        client,
        viewer,
        base,
        kind="sprite",
        name="No",
        data=rgba_png(),
        filename="x.png",
        media="image/png",
    )
    assert denied.status_code == 403
    foreign = (
        await client.post("/v1/workspaces", headers=headers, json={"name": "Other studio"})
    ).json()
    assert (
        await client.get(f"{base}/assets", headers={**headers, "X-Tenant-ID": foreign["id"]})
    ).status_code == 404
    head = (await client.get(base, headers=headers)).json()["head_revision_id"]
    await client.post(
        f"{base}/archive", headers=headers, json={"base_revision_id": head, "archived": True}
    )
    refused = await upload(
        client,
        headers,
        base,
        kind="sprite",
        name="Late",
        data=rgba_png(),
        filename="x.png",
        media="image/png",
    )
    assert refused.status_code == 409
