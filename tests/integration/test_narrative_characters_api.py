"""Character profiles, portrait jobs and immutable images (ADR 0039); no GPU or Temporal."""

import hashlib
import struct
import zlib
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from flint_graph.api.dependencies import get_narrative_artifact_store
from flint_graph.application.narrative_image_workflow import (
    CANCELLED_TOPIC,
    IMAGE_WORKFLOW,
    QUEUED_TOPIC,
    RUN_IMAGE_ACTIVITY,
    ImageJobPayload,
    image_job_workflow_id,
)
from flint_graph.application.services.narrative_image_relay import (
    recover_stale_image_jobs,
    relay_image_batch,
)
from flint_graph.application.services.narrative_images import register_image_workflow
from flint_graph.config import Settings, get_settings
from flint_graph.domain.enums import OutboxMessageStatus
from flint_graph.infrastructure.db.models import NarrativeAsset, NarrativeImageJob, OutboxMessage
from flint_graph.infrastructure.narrative_artifact_store import ArtifactStoreError
from flint_graph.infrastructure.narrative_imagegen import (
    CutoutModel,
    GeneratedImage,
    GenerationResult,
    ImageGenerationError,
    IpAdapterModel,
    ModelIdentity,
)
from flint_graph.main import app
from flint_graph.narrative.imagegen import HIRES_SCALE, HIRES_STRENGTH, HiresFix
from flint_graph.worker.activities.narrative_image import NarrativeImageActivities

MODEL = ModelIdentity("cagliostrolab/animagine-xl-4.0", "c" * 40, "openrail++")
SEGMENTER = CutoutModel(
    path=Path("isnetis.onnx"),
    sha256="f" * 64,
    identity=ModelIdentity("skytnt/anime-seg", "4" * 40, "apache-2.0"),
)
ADAPTER = ModelIdentity("h94/IP-Adapter", "1" * 40, "apache-2.0")
IP_ADAPTER = IpAdapterModel(
    root=Path("ip-adapter"),
    weight="sdxl_models/ip-adapter-plus_sdxl_vit-h.safetensors",
    encoder="models/image_encoder",
    identity=ADAPTER,
)
# Where the fake segmenter finds the figure inside an 832x1216 render.
BOX = (160, 30, 672, 1200)


def png(width, height, shade=10, seed=0, alpha=False):
    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    opacity = [255] if alpha else []
    row = b"\x00" + bytes([shade, 20, 30, *opacity]) * width
    # The first row carries the seed, so separately generated images differ.
    first = b"\x00" + bytes([seed & 255, (seed >> 8) & 255, (seed >> 16) & 255, *opacity]) * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6 if alpha else 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(first + row * (height - 1)))
        + chunk(b"IEND", b"")
    )


class MemoryStore:
    def __init__(self):
        self.objects = {}

    async def put_once(self, key, data, *, expected_sha256, content_type, max_bytes):
        assert content_type in ("image/png", "font/ttf", "font/otf", "audio/wav")
        assert len(data) <= max_bytes
        assert hashlib.sha256(data).hexdigest() == expected_sha256
        self.objects[key] = data

    async def delete_reference(self, key):
        assert "/voice-references/" in key
        self.objects.pop(key, None)

    async def get_verified(self, key, *, expected_size, expected_sha256, max_bytes):
        data = self.objects.get(key)
        if data is None or hashlib.sha256(data).hexdigest() != expected_sha256:
            raise ArtifactStoreError("artifact_integrity")
        assert len(data) == expected_size <= max_bytes
        return data


class FakeGenerator:
    model = MODEL

    def __init__(self, *failures, skip_cutout=False, skip_adapter=False):
        self.failures, self.requests, self.skip_cutout = list(failures), [], skip_cutout
        self.skip_adapter = skip_adapter

    async def generate(self, request, *, on_progress):
        self.requests.append(request)
        if self.failures:
            raise ImageGenerationError(self.failures.pop(0))
        cut = request.cutout and not self.skip_cutout
        scale = request.hires.scale if request.hires else 1
        box = tuple(round(value * scale) for value in BOX)
        width, height = (
            (box[2] - box[0], box[3] - box[1])
            if cut
            else (round(request.width * scale), round(request.height * scale))
        )
        # A repainted face keeps the base's size and transparency.
        alpha = cut or (request.inpaint is not None and request.inpaint.image[25] == 6)
        images = []
        for index, seed in enumerate(request.seeds):
            data = png(width, height, index, seed, alpha=alpha)
            thumb = png(16, 24, index, seed, alpha=alpha)
            images.append(
                GeneratedImage(
                    index=index,
                    seed=seed,
                    data=data,
                    sha256=hashlib.sha256(data).hexdigest(),
                    width=width,
                    height=height,
                    thumbnail=thumb,
                    thumbnail_sha256=hashlib.sha256(thumb).hexdigest(),
                    thumbnail_width=16,
                    thumbnail_height=24,
                    box=box if cut else None,
                )
            )
            await on_progress(index + 1)
        return GenerationResult(
            images=tuple(images),
            runtime={"torch": "fake", "diffusers": "fake", "cuda": "0", "device": "Fake"},
            prompt_tokens=20,
            truncated=False,
            cutout=SEGMENTER if cut else None,
            ip_adapter=IP_ADAPTER if request.scene and not self.skip_adapter else None,
        )


class Releaser:
    def __init__(self):
        self.calls = 0

    async def release(self):
        self.calls += 1


class Dispatcher:
    def __init__(self, closed=False):
        self.started, self.cancelled, self.run_id, self.is_closed = [], [], uuid4(), closed

    async def start(self, payload):
        self.started.append(payload)
        return self.run_id

    async def cancel(self, payload, *, run_id):
        self.cancelled.append((payload, run_id))

    async def closed(self, payload, *, run_id):
        return self.is_closed


def use_settings(enabled=True):
    # Keep the suite's OIDC test settings so roles are enforced as in production.
    original = app.dependency_overrides.get(get_settings, lambda: Settings(env="test"))
    configured = original().model_copy(update={"narrative_image_generation_enabled": enabled})
    app.dependency_overrides[get_settings] = lambda: configured
    return original


@pytest.fixture
async def studio(narrative_env, oidc_auth):
    client, factory, _ = narrative_env
    original = use_settings()
    store = MemoryStore()
    app.dependency_overrides[get_narrative_artifact_store] = lambda: store
    owner = {"Authorization": "Bearer " + oidc_auth("character-owner")}
    try:
        workspace = (
            await client.post("/v1/workspaces", headers=owner, json={"name": "Characters"})
        ).json()
        headers = {**owner, "X-Tenant-ID": workspace["id"]}
        project = (
            await client.post(
                "/v1/narrative/projects",
                headers=headers,
                json={"name": "Lighthouse", "idempotency_key": str(uuid4())},
            )
        ).json()
        base = f"/v1/narrative/projects/{project['id']}"
        yield client, factory, store, headers, base, workspace, oidc_auth
    finally:
        app.dependency_overrides[get_settings] = original
        app.dependency_overrides.pop(get_narrative_artifact_store, None)


def job_body(**changes):
    return {
        "appearance": "silver hair, amber eyes, navy coat",
        "character_type": "woman",
        "framing": "portrait",
        "count": 2,
        "idempotency_key": str(uuid4()),
        **changes,
    }


def environment(payload, run_id, attempt=1):
    env = ActivityEnvironment()
    env.info = replace(
        env.info,
        activity_type=RUN_IMAGE_ACTIVITY,
        workflow_id=image_job_workflow_id(payload),
        workflow_type=IMAGE_WORKFLOW,
        workflow_run_id=str(run_id),
        attempt=attempt,
    )
    return env


async def queue_job(client, headers, base, character="mira", **changes):
    response = await client.post(
        f"{base}/characters/{character}/portrait-jobs", headers=headers, json=job_body(**changes)
    )
    assert response.status_code == 202, response.text
    job = response.json()
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=job["id"]
    )
    return job, payload


async def registered(factory, payload):
    run_id = uuid4()
    async with factory() as session:
        await register_image_workflow(
            session,
            tenant_id=UUID(payload["tenant_id"]),
            job_id=UUID(payload["job_id"]),
            workflow_run_id=run_id,
        )
        await session.commit()
    return run_id


async def run_job(factory, store, payload, generator=None, attempt=1, releaser=None, run_id=None):
    run_id = run_id or await registered(factory, payload)
    work = NarrativeImageActivities(
        factory=factory, generator=generator or FakeGenerator(), store=store, releaser=releaser
    )
    return await environment(payload, run_id, attempt).run(work.run, payload)


async def job_row(factory, payload):
    async with factory() as session:
        return await session.scalar(
            select(NarrativeImageJob).where(NarrativeImageJob.id == UUID(payload["job_id"]))
        )


@pytest.mark.anyio
async def test_profiles_save_with_versions_and_respect_roles(studio):
    client, _, _, headers, base, workspace, oidc_auth = studio
    assert (await client.get(f"{base}/characters", headers=headers)).json() == {
        "project_id": base.rsplit("/", 1)[1],
        "profiles": [],
    }
    body = {"base_version": 0, "appearance": "tall", "character_type": "man", "framing": "portrait"}
    saved = await client.put(f"{base}/characters/oren", headers=headers, json=body)
    assert saved.status_code == 200
    assert saved.json() == {
        "character_id": "oren",
        "appearance": "tall",
        "character_type": "man",
        "framing": "portrait",
        "portrait": None,
        "voice": None,
        "version": 1,
    }
    stale = await client.put(f"{base}/characters/oren", headers=headers, json=body)
    assert stale.status_code == 409 and stale.json()["type"].endswith("stale-character")
    updated = await client.put(
        f"{base}/characters/oren", headers=headers, json={**body, "base_version": 1}
    )
    assert updated.json()["version"] == 2
    listed = (await client.get(f"{base}/characters", headers=headers)).json()["profiles"]
    assert [item["character_id"] for item in listed] == ["oren"]
    for path, payload in [
        (f"{base}/characters/Oren", body),
        (f"{base}/characters/oren", {**body, "appearance": "x" * 601}),
        (f"{base}/characters/oren", {**body, "character_type": "robot"}),
        (f"{base}/characters/oren", {**body, "extra": 1}),
    ]:
        assert (await client.put(path, headers=headers, json=payload)).status_code == 422

    added = await client.post(
        f"/v1/workspaces/{workspace['id']}/members",
        headers=headers,
        json={
            "oidc_issuer": "https://keycloak.example/realms/flintgraph",
            "oidc_subject": "character-viewer",
            "role": "viewer",
        },
    )
    assert added.status_code == 201, added.text
    viewer = {**headers, "Authorization": "Bearer " + oidc_auth("character-viewer")}
    assert (await client.get(f"{base}/characters", headers=viewer)).status_code == 200
    denied = await client.put(f"{base}/characters/oren", headers=viewer, json=body)
    assert denied.status_code == 403
    denied_job = await client.post(
        f"{base}/characters/oren/portrait-jobs", headers=viewer, json=job_body()
    )
    assert denied_job.status_code == 403
    foreign = (
        await client.post("/v1/workspaces", headers=headers, json={"name": "Elsewhere"})
    ).json()
    elsewhere = {**headers, "X-Tenant-ID": foreign["id"]}
    assert (await client.get(f"{base}/characters", headers=elsewhere)).status_code == 404
    head = (await client.get(base, headers=headers)).json()["head_revision_id"]
    archived = await client.post(
        f"{base}/archive", headers=headers, json={"base_revision_id": head, "archived": True}
    )
    assert archived.status_code == 200, archived.text
    frozen = await client.put(
        f"{base}/characters/oren", headers=headers, json={**body, "base_version": 2}
    )
    assert frozen.status_code == 409


@pytest.mark.anyio
async def test_portrait_jobs_are_built_server_side_idempotent_and_bounded(studio):
    client, factory, _, headers, base, *_ = studio
    body = job_body()
    created = await client.post(f"{base}/characters/mira/portrait-jobs", headers=headers, json=body)
    assert created.status_code == 202
    job = created.json()
    assert job["status"] == "queued" and job["count"] == 2 and len(job["seeds"]) == 2
    assert job["prompt"].startswith("1girl, mature female, solo, silver hair, amber eyes")
    assert (job["width"], job["height"], job["steps"], job["guidance"]) == (832, 1216, 28, 5.0)
    replay = await client.post(f"{base}/characters/mira/portrait-jobs", headers=headers, json=body)
    assert replay.status_code == 202 and replay.json()["id"] == job["id"]
    changed = await client.post(
        f"{base}/characters/mira/portrait-jobs",
        headers=headers,
        json={**body, "appearance": "different"},
    )
    assert changed.status_code == 409
    for bad in [job_body(count=0), job_body(count=5), job_body(appearance=""), job_body(x=1)]:
        response = await client.post(
            f"{base}/characters/mira/portrait-jobs", headers=headers, json=bad
        )
        assert response.status_code == 422
    await queue_job(client, headers, base, character="oren")
    limited = await client.post(
        f"{base}/characters/mira/portrait-jobs", headers=headers, json=job_body()
    )
    assert limited.status_code == 429
    jobs = (await client.get(f"{base}/characters/mira/portrait-jobs", headers=headers)).json()
    assert [item["id"] for item in jobs["jobs"]] == [job["id"]]
    async with factory() as session:
        [message] = [
            m
            for m in await session.scalars(select(OutboxMessage))
            if m.aggregate_id == UUID(job["id"])
        ]
    assert message.topic == QUEUED_TOPIC
    assert set(message.payload) == {"schema_version", "tenant_id", "job_id"}, "IDs only"


@pytest.mark.anyio
async def test_the_content_policy_file_refuses_blocked_words_and_leads_negatives(
    studio, tmp_path
):
    client, _, _, headers, base, *_ = studio
    jobs = f"{base}/characters/mira/portrait-jobs"
    nude = job_body(appearance="silver hair, Nude")
    refused = await client.post(jobs, headers=headers, json=nude)
    assert refused.status_code == 422 and '"nude" is blocked' in refused.json()["detail"]
    policy = tmp_path / "policy.toml"
    policy.write_text('version = 1\nnegative = ["sensitive"]\nblocked = ["gore"]\n', "utf-8")
    custom = app.dependency_overrides[get_settings]().model_copy(
        update={"narrative_image_content_policy": str(policy)}
    )
    app.dependency_overrides[get_settings] = lambda: custom
    gore = await client.post(jobs, headers=headers, json=job_body(appearance="silver hair, gore"))
    assert gore.status_code == 422 and '"gore" is blocked' in gore.json()["detail"]
    created = await client.post(jobs, headers=headers, json=job_body())
    assert created.status_code == 202
    assert created.json()["negative_prompt"].startswith("sensitive, lowres, ")
    background = await client.post(
        f"{base}/assets/background-jobs",
        headers=headers,
        json={"description": "a gore-free harbor", "count": 1, "idempotency_key": str(uuid4())},
    )
    assert background.status_code == 422 and '"gore" is blocked' in background.json()["detail"]
    with pytest.raises(ValueError):
        Settings(env="test", narrative_image_content_policy=str(tmp_path / "missing.toml"))


@pytest.mark.anyio
async def test_disabled_generation_refuses_jobs_but_profiles_still_work(studio):
    client, _, _, headers, base, *_ = studio
    disabled = app.dependency_overrides[get_settings]().model_copy(
        update={"narrative_image_generation_enabled": False}
    )
    app.dependency_overrides[get_settings] = lambda: disabled
    refused = await client.post(
        f"{base}/characters/mira/portrait-jobs", headers=headers, json=job_body()
    )
    assert refused.status_code == 503 and refused.json()["type"].endswith(
        "image-generation-unavailable"
    )
    body = {"base_version": 0, "appearance": "", "character_type": "other", "framing": "full_body"}
    assert (
        await client.put(f"{base}/characters/mira", headers=headers, json=body)
    ).status_code == 200


@pytest.mark.anyio
async def test_relay_runs_the_job_and_stores_verified_candidates(studio):
    client, factory, store, headers, base, *_ = studio
    job, payload = await queue_job(client, headers, base)
    dispatcher = Dispatcher()
    assert await relay_image_batch(factory, dispatcher=dispatcher) == 1
    assert dispatcher.started == [payload]
    outcome = await run_job(factory, store, payload, run_id=dispatcher.run_id)
    assert outcome == {"job_id": job["id"], "status": "completed"}
    done = (await client.get(f"{base}/image-jobs/{job['id']}", headers=headers)).json()
    assert done["status"] == "completed" and done["progress"] == 2
    assert done["model"] == f"{MODEL.repo}@{MODEL.revision}"
    assert done["transparent"] is False and done["cutout"] is None
    assert [asset["status"] for asset in done["assets"]] == ["candidate", "candidate"]
    assert {asset["kind"] for asset in done["assets"]} == {"character_portrait"}
    assert "cutout" not in done["assets"][0]["provenance"]
    asset = done["assets"][0]
    assert asset["seed"] == job["seeds"][0] and asset["license"] == "openrail++"
    assert asset["provenance"]["prompt"] == job["prompt"]
    assert asset["provenance"]["model_revision"] == MODEL.revision
    image = await client.get(f"{base}/assets/{asset['id']}/content", headers=headers)
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert hashlib.sha256(image.content).hexdigest() == asset["sha256"]
    assert "immutable" in image.headers["cache-control"]
    assert image.headers["x-content-type-options"] == "nosniff"
    thumb = await client.get(
        f"{base}/assets/{asset['id']}/content?variant=thumbnail", headers=headers
    )
    assert thumb.status_code == 200 and thumb.content.startswith(b"\x89PNG")
    replay = await run_job(factory, store, payload, attempt=2, run_id=dispatcher.run_id)
    assert replay["status"] == "stale", "A finished job never runs again"
    store.objects.clear()
    missing = await client.get(f"{base}/assets/{asset['id']}/content", headers=headers)
    assert missing.status_code == 503


@pytest.mark.anyio
async def test_transparent_jobs_cut_out_full_body_sprites_for_the_library(studio):
    client, factory, store, headers, base, *_ = studio
    for bad in (job_body(transparent=True), job_body(framing="full_body", transparent="yes")):
        refused = await client.post(
            f"{base}/characters/mira/portrait-jobs", headers=headers, json=bad
        )
        assert refused.status_code == 422, "Sprites need full-body framing"
    body = job_body(framing="full_body", transparent=True)
    created = await client.post(f"{base}/characters/mira/portrait-jobs", headers=headers, json=body)
    assert created.status_code == 202, created.text
    job = created.json()
    assert job["transparent"] is True and job["cutout"] is None
    assert "full body, standing, white background, " in job["prompt"]
    assert "gradient background" in job["negative_prompt"]
    changed = await client.post(
        f"{base}/characters/mira/portrait-jobs",
        headers=headers,
        json={**body, "transparent": False},
    )
    assert changed.status_code == 409, "The flag is part of the request identity"
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=job["id"]
    )
    generator = FakeGenerator()
    outcome = await run_job(factory, store, payload, generator)
    assert outcome["status"] == "completed"
    assert [request.cutout for request in generator.requests] == [True]
    done = (await client.get(f"{base}/image-jobs/{job['id']}", headers=headers)).json()
    assert done["cutout"] == {"model": "skytnt/anime-seg@" + "4" * 40, "sha256": SEGMENTER.sha256}
    assert [asset["kind"] for asset in done["assets"]] == ["sprite", "sprite"]
    assert [asset["name"] for asset in done["assets"]] == ["mira sprite 1", "mira sprite 2"]
    sprite = done["assets"][0]
    assert sprite["status"] == "candidate" and sprite["character_id"] == "mira"
    assert (sprite["width"], sprite["height"]) == (BOX[2] - BOX[0], BOX[3] - BOX[1])
    assert sprite["license"] == "openrail++", "The image model's licence governs the output"
    assert sprite["provenance"]["width"] == 832, "Provenance keeps the generation size"
    assert sprite["provenance"]["cutout"] == {
        "model_repo": "skytnt/anime-seg",
        "model_revision": "4" * 40,
        "sha256": SEGMENTER.sha256,
        "license": "apache-2.0",
        "box": list(BOX),
    }
    content = await client.get(f"{base}/assets/{sprite['id']}/content", headers=headers)
    assert content.content[24:26] == bytes([8, 6]), "Stored as 8-bit RGBA"
    listed = (await client.get(f"{base}/characters/mira/portrait-jobs", headers=headers)).json()
    assert listed["jobs"][0]["id"] == job["id"] and listed["jobs"][0]["transparent"] is True
    chosen = await client.put(
        f"{base}/characters/mira/portrait",
        headers=headers,
        json={"base_version": 0, "asset_id": sprite["id"]},
    )
    assert chosen.status_code == 409, "A sprite is not a portrait"
    approved = await client.post(f"{base}/assets/{sprite['id']}/approve", headers=headers)
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    library = (await client.get(f"{base}/assets?kind=sprite", headers=headers)).json()
    assert sprite["id"] in [asset["id"] for asset in library["assets"]]
    async with factory() as session:
        row = await session.get(NarrativeImageJob, UUID(job["id"]))
        assert row is not None and row.cutout_sha256 == SEGMENTER.sha256


@pytest.mark.anyio
async def test_high_resolution_jobs_upscale_the_render_and_record_the_hires_fix(studio):
    client, factory, store, headers, base, *_ = studio
    refused = await client.post(
        f"{base}/characters/mira/portrait-jobs", headers=headers, json=job_body(hires="yes")
    )
    assert refused.status_code == 422
    body = job_body(framing="full_body", transparent=True, hires=True)
    created = await client.post(f"{base}/characters/mira/portrait-jobs", headers=headers, json=body)
    assert created.status_code == 202, created.text
    job = created.json()
    assert job["hires"] == {"scale": HIRES_SCALE, "strength": HIRES_STRENGTH}
    assert (job["width"], job["height"]) == (832, 1216), "The base render"
    output = (round(832 * HIRES_SCALE), round(1216 * HIRES_SCALE))
    assert (job["output_width"], job["output_height"]) == output
    changed = await client.post(
        f"{base}/characters/mira/portrait-jobs", headers=headers, json={**body, "hires": False}
    )
    assert changed.status_code == 409, "The flag is part of the request identity"
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=job["id"]
    )
    generator = FakeGenerator()
    assert (await run_job(factory, store, payload, generator))["status"] == "completed"
    assert [request.hires for request in generator.requests] == [
        HiresFix(scale=HIRES_SCALE, strength=HIRES_STRENGTH)
    ]
    done = (await client.get(f"{base}/image-jobs/{job['id']}", headers=headers)).json()
    sprite = done["assets"][0]
    box = [round(value * HIRES_SCALE) for value in BOX]
    assert (sprite["width"], sprite["height"]) == (box[2] - box[0], box[3] - box[1])
    assert sprite["provenance"]["width"] == 832, "Provenance keeps the generation size"
    assert sprite["provenance"]["hires"] == {"scale": HIRES_SCALE, "strength": HIRES_STRENGTH}
    assert sprite["provenance"]["cutout"]["box"] == box
    standard, standard_payload = await queue_job(client, headers, base, character="oren")
    assert standard["hires"] is None
    assert (standard["output_width"], standard["output_height"]) == (832, 1216)
    await run_job(factory, store, standard_payload, generator)
    assert generator.requests[-1].hires is None
    opaque = (await client.get(f"{base}/image-jobs/{standard['id']}", headers=headers)).json()
    assert "hires" not in opaque["assets"][0]["provenance"]


@pytest.mark.anyio
async def test_a_transparent_job_without_a_cutout_fails_instead_of_storing_opaque_sprites(studio):
    client, factory, store, headers, base, *_ = studio
    job, payload = await queue_job(client, headers, base, framing="full_body", transparent=True)
    outcome = await run_job(factory, store, payload, FakeGenerator(skip_cutout=True))
    assert outcome["status"] == "failed"
    done = (await client.get(f"{base}/image-jobs/{job['id']}", headers=headers)).json()
    assert done["error_code"] == "invalid_output" and done["assets"] == []
    assert done["cutout"] is None
    async with factory() as session:
        assert list(await session.scalars(select(NarrativeAsset))) == []


@pytest.mark.anyio
async def test_choosing_a_portrait_approves_it_and_discards_are_guarded(studio):
    client, factory, store, headers, base, *_ = studio
    job, payload = await queue_job(client, headers, base)
    await run_job(factory, store, payload)
    first, second = (await client.get(f"{base}/image-jobs/{job['id']}", headers=headers)).json()[
        "assets"
    ]
    chosen = await client.put(
        f"{base}/characters/mira/portrait",
        headers=headers,
        json={"base_version": 0, "asset_id": first["id"]},
    )
    assert chosen.status_code == 200, chosen.text
    profile = chosen.json()
    assert profile["version"] == 1 and profile["portrait"]["id"] == first["id"]
    assert profile["portrait"]["status"] == "approved"
    blocked = await client.post(f"{base}/assets/{first['id']}/discard", headers=headers)
    assert blocked.status_code == 409
    discarded = await client.post(f"{base}/assets/{second['id']}/discard", headers=headers)
    assert discarded.status_code == 200 and discarded.json()["status"] == "discarded"
    refused = await client.put(
        f"{base}/characters/mira/portrait",
        headers=headers,
        json={"base_version": 1, "asset_id": second["id"]},
    )
    assert refused.status_code == 409
    listed = (await client.get(f"{base}/characters/mira/portrait-jobs", headers=headers)).json()
    assert [asset["id"] for asset in listed["jobs"][0]["assets"]] == [first["id"]]
    cleared = await client.put(
        f"{base}/characters/mira/portrait",
        headers=headers,
        json={"base_version": 1, "asset_id": None},
    )
    assert cleared.json()["portrait"] is None
    assert (
        await client.post(f"{base}/assets/{first['id']}/discard", headers=headers)
    ).status_code == 200
    unknown = await client.put(
        f"{base}/characters/mira/portrait",
        headers=headers,
        json={"base_version": 2, "asset_id": str(uuid4())},
    )
    assert unknown.status_code == 404


@pytest.mark.anyio
async def test_cancellation_before_and_during_execution(studio):
    client, factory, store, headers, base, *_ = studio
    job, payload = await queue_job(client, headers, base)
    cancelled = await client.post(f"{base}/image-jobs/{job['id']}/cancel", headers=headers)
    assert cancelled.json()["status"] == "cancelled"
    dispatcher = Dispatcher()
    assert await relay_image_batch(factory, dispatcher=dispatcher) == 1
    assert dispatcher.started == []

    job, payload = await queue_job(client, headers, base)
    run_id = await registered(factory, payload)

    class CancelledDuringRun(FakeGenerator):
        async def generate(self, request, *, on_progress):
            response = await client.post(f"{base}/image-jobs/{job['id']}/cancel", headers=headers)
            assert response.json()["cancel_requested"] is True
            return await super().generate(request, on_progress=on_progress)

    outcome = await run_job(factory, store, payload, CancelledDuringRun(), run_id=run_id)
    assert outcome["status"] == "cancelled"
    assert store.objects == {} or (await job_row(factory, payload)).status == "cancelled"
    async with factory() as session:
        assets = list(
            await session.scalars(
                select(NarrativeAsset).where(NarrativeAsset.job_id == UUID(job["id"]))
            )
        )
        cancels = list(
            await session.scalars(
                select(OutboxMessage).where(OutboxMessage.topic == CANCELLED_TOPIC)
            )
        )
    assert assets == [] and len(cancels) == 1


@pytest.mark.anyio
async def test_gpu_contention_retries_releases_ollama_and_fails_with_a_safe_code(studio):
    client, factory, store, headers, base, *_ = studio
    _, payload = await queue_job(client, headers, base)
    run_id = await registered(factory, payload)
    with pytest.raises(ApplicationError) as raised:
        await run_job(factory, store, payload, FakeGenerator("gpu_busy"), run_id=run_id)
    assert raised.value.type == "gpu_busy" and not raised.value.non_retryable
    assert (await job_row(factory, payload)).status == "running"
    failed = await run_job(
        factory, store, payload, FakeGenerator("gpu_busy"), attempt=3, run_id=run_id
    )
    assert failed["status"] == "failed"
    assert (await job_row(factory, payload)).error_code == "gpu_busy"

    _, payload = await queue_job(client, headers, base, character="oren")
    releaser = Releaser()
    generator = FakeGenerator("gpu_busy")
    outcome = await run_job(factory, store, payload, generator, releaser=releaser)
    assert outcome["status"] == "completed"
    assert releaser.calls == 1 and len(generator.requests) == 2


@pytest.mark.anyio
async def test_unregistered_and_foreign_runs_cannot_claim_and_recovery_closes_lost_runs(studio):
    client, factory, store, headers, base, *_ = studio
    _, payload = await queue_job(client, headers, base)
    work = NarrativeImageActivities(
        factory=factory, generator=FakeGenerator(), store=store, releaser=None
    )
    with pytest.raises(ApplicationError) as raised:
        await environment(payload, uuid4()).run(work.run, payload)
    assert raised.value.type == "registration_pending"
    run_id = await registered(factory, payload)
    assert (await environment(payload, uuid4()).run(work.run, payload))["status"] == "stale"
    assert (await job_row(factory, payload)).status == "queued"
    async with factory() as session:
        row = await session.get(NarrativeImageJob, UUID(payload["job_id"]))
        row.created_at = row.created_at.replace(year=2020)
        await session.commit()
    assert await recover_stale_image_jobs(factory, dispatcher=Dispatcher(closed=False)) == 0
    assert await recover_stale_image_jobs(factory, dispatcher=Dispatcher(closed=True)) == 1
    job = await job_row(factory, payload)
    assert (job.status, job.error_code, job.workflow_run_id) == (
        "failed",
        "worker_interrupted",
        run_id,
    )
    async with factory() as session:
        published = await session.scalar(
            select(OutboxMessage).where(OutboxMessage.aggregate_id == UUID(payload["job_id"]))
        )
    assert published.status == OutboxMessageStatus.PENDING


@pytest.mark.anyio
async def test_expression_jobs_repaint_the_face_of_a_base_sprite(studio):
    client, factory, store, headers, base, *_ = studio
    sprite = png(300, 500, 40, 7, alpha=True)
    uploaded = await client.post(
        f"{base}/assets",
        headers=headers,
        data={"kind": "sprite", "name": "Mira base", "license": "Own work", "notice": "",
              "rights_declared": "true"},
        files={"file": ("mira.png", sprite, "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    asset = uploaded.json()
    profile = {"base_version": 0, "appearance": "shoulder-length white hair, red eyes",
               "character_type": "girl", "framing": "full_body"}
    saved = await client.put(f"{base}/characters/mira", headers=headers, json=profile)
    assert saved.status_code == 200
    body = {"base_asset_id": asset["id"], "face_box": [100, 20, 160, 80],
            "expressions": ["happy", "Fond of tea"], "idempotency_key": str(uuid4())}
    path = f"{base}/characters/mira/expression-jobs"
    for bad, status in (
        ({"face_box": [250, 20, 310, 80]}, 422),
        ({"face_box": [100, 20, 110, 80]}, 422),
        ({"face_box": [100, 20, 200, 30]}, 422),
        ({"base_asset_id": str(uuid4())}, 404),
        ({"expressions": ["a", "b", "c", "d", "e"]}, 422),
        ({"expressions": ["<b>"]}, 422),
    ):
        attempt = {**body, **bad, "idempotency_key": str(uuid4())}
        refused = await client.post(path, headers=headers, json=attempt)
        assert refused.status_code == status, (bad, refused.text)
        if status == 422 and "face_box" not in bad and len(bad["expressions"]) < 5:
            assert refused.json()["type"].endswith("invalid-expression-request")
    created = await client.post(path, headers=headers, json=body)
    assert created.status_code == 202, created.text
    job = created.json()
    shape = (job["purpose"], job["count"], job["width"], job["height"])
    assert shape == ("character_expression", 2, 300, 500)
    assert job["expressions"] == ["happy", "fond_of_tea"] and job["strength"] == 0.9
    assert job["face_box"] == [100, 20, 160, 80] and job["base_asset_id"] == asset["id"]
    assert job["prompts"][0].startswith("1girl, solo, close-up, face, smile, open mouth, happy, ")
    assert "white hair" in job["prompts"][1] and "fond of tea" in job["prompts"][1]
    assert (await client.post(path, headers=headers, json=body)).json()["id"] == job["id"]
    changed = await client.post(path, headers=headers, json={**body, "expressions": ["sad"]})
    assert changed.status_code == 409
    generator = FakeGenerator()
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=job["id"]
    )
    assert (await run_job(factory, store, payload, generator))["status"] == "completed"
    sent = generator.requests[0]
    assert sent.inpaint.image == sprite and sent.inpaint.box == (100, 20, 160, 80)
    assert sent.inpaint.prompts == tuple(job["prompts"]) and (sent.width, sent.height) == (300, 500)
    listed = (await client.get(path, headers=headers)).json()["jobs"]
    assert [item["id"] for item in listed] == [job["id"]]
    results = listed[0]["assets"]
    assert [item["name"] for item in results] == ["mira happy", "mira fond_of_tea"]
    assert {item["kind"] for item in results} == {"sprite"}
    assert results[0]["provenance"]["expression"] == "happy"
    assert results[0]["provenance"]["base_asset_id"] == asset["id"]
    assert results[1]["provenance"]["prompt"] == job["prompts"][1]
    content = await client.get(f"{base}/assets/{results[0]['id']}/content", headers=headers)
    assert content.content[25] == 6, "the expression stays a transparent sprite"
    # A discarded base cannot start new expressions.
    await client.post(f"{base}/assets/{asset['id']}/discard", headers=headers)
    gone = await client.post(path, headers=headers, json={**body, "idempotency_key": str(uuid4())})
    assert gone.status_code == 404
    # High-resolution sprites (up to 1664 x 2432) are bases too; larger images are not.
    for height, status in ((2432, 202), (2600, 422)):
        tall = await client.post(
            f"{base}/assets",
            headers=headers,
            data={"kind": "sprite", "name": f"Mira {height}", "license": "Own work",
                  "notice": "", "rights_declared": "true"},
            files={"file": ("tall.png", png(200, height, 40, height, alpha=True), "image/png")},
        )
        assert tall.status_code == 201, tall.text
        attempt = {**body, "base_asset_id": tall.json()["id"], "idempotency_key": str(uuid4())}
        started = await client.post(path, headers=headers, json=attempt)
        assert started.status_code == status, started.text
