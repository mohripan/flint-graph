"""Generated music: jobs, the execution fence, candidates and binding (ADR 0067)."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment
from test_narrative_package_v2_api import configure, head, save, v2  # noqa: F401

from flint_graph.application.narrative_image_workflow import (
    MUSIC_CANCELLED_TOPIC,
    MUSIC_QUEUED_TOPIC,
    MUSIC_WORKFLOW,
    RUN_MUSIC_ACTIVITY,
    ImageJobPayload,
    music_job_workflow_id,
)
from flint_graph.application.services.narrative_music import register_music_workflow
from flint_graph.config import Settings
from flint_graph.infrastructure.db.models import NarrativeAsset, NarrativeMusicJob, OutboxMessage
from flint_graph.infrastructure.narrative_imagegen import ModelIdentity
from flint_graph.infrastructure.narrative_musicgen import (
    GeneratedTrack,
    MusicGenerationError,
    MusicResult,
)
from flint_graph.worker.activities.narrative_music import NarrativeMusicActivities

MODEL = ModelIdentity("ACE-Step/ACE-Step-v1-3.5B", "8" * 40, "apache-2.0")
RUNTIME = {"torch": "2.11.0+cu128", "cuda": "12.8", "device": "GPU"}
TONE = (Path(__file__).parents[1] / "fixtures/narrative/audio/tone_a.ogg").read_bytes()


class FakeMusic:
    model = MODEL

    def __init__(self, *failures):
        self.failures, self.requests = list(failures), []

    async def generate(self, request, *, on_progress):
        self.requests.append(request)
        if self.failures:
            raise MusicGenerationError(self.failures.pop(0))
        await on_progress(1)
        track = GeneratedTrack(TONE, hashlib.sha256(TONE).hexdigest(), 2000, 2, 44100)
        return MusicResult(track=track, runtime=RUNTIME)


class Releaser:
    def __init__(self):
        self.calls = 0

    async def release(self):
        self.calls += 1


async def registered_run(factory, payload):
    run_id = uuid4()
    async with factory() as session:
        await register_music_workflow(
            session,
            tenant_id=UUID(payload["tenant_id"]),
            job_id=UUID(payload["job_id"]),
            workflow_run_id=run_id,
        )
        await session.commit()
    return run_id


async def run_music_job(
    factory, store, payload, generator=None, attempt=1, releaser=None, run_id=None
):
    run_id = run_id or await registered_run(factory, payload)
    env = ActivityEnvironment()
    env.info = replace(
        env.info,
        activity_type=RUN_MUSIC_ACTIVITY,
        workflow_id=music_job_workflow_id(payload),
        workflow_type=MUSIC_WORKFLOW,
        workflow_run_id=str(run_id),
        attempt=attempt,
    )
    work = NarrativeMusicActivities(
        factory=factory, generator=generator or FakeMusic(), store=store, releaser=releaser
    )
    return await env.run(work.run, payload)


async def request_track(client, headers, base, *, description="calm piano", seconds=60, key=None):
    return await client.post(
        f"{base}/music-jobs",
        headers=headers,
        json={
            "description": description,
            "seconds": seconds,
            "idempotency_key": str(key or uuid4()),
        },
    )


def payload_of(tenant, job_id) -> ImageJobPayload:
    return ImageJobPayload(schema_version="1", tenant_id=str(tenant), job_id=str(job_id))


@pytest.mark.anyio
async def test_a_request_becomes_one_candidate_track_to_review(v2):  # noqa: F811
    client, factory, store, headers, project = v2
    base, _ = await project(schema="2")
    tenant = headers["X-Tenant-ID"]
    configure(narrative_music_generation_enabled=True)

    created = await request_track(client, headers, base, description="  calm   piano ")
    assert created.status_code == 201, created.text
    job = created.json()
    assert (job["status"], job["seconds"], job["description"]) == ("queued", 60, "calm piano")

    # Admission writes the outbox message in the same transaction, and only IDs.
    async with factory() as session:
        message = await session.scalar(
            select(OutboxMessage).where(OutboxMessage.topic == MUSIC_QUEUED_TOPIC)
        )
        assert set(message.payload) == {"schema_version", "tenant_id", "job_id"}

    generator = FakeMusic()
    outcome = await run_music_job(factory, store, payload_of(tenant, job["id"]), generator)
    assert outcome == {"job_id": job["id"], "status": "completed"}
    assert generator.requests[0].description == "calm piano"
    assert generator.requests[0].seconds == 60

    finished = (await client.get(f"{base}/music-jobs/{job['id']}", headers=headers)).json()
    assert (finished["status"], finished["progress"]) == ("completed", 1)
    assert finished["model"] == f"{MODEL.repo}@{MODEL.revision}"
    assert finished["runtime"] == RUNTIME
    track = finished["assets"][0]
    assert (track["kind"], track["status"], track["source"]) == ("music", "candidate", "generated")
    assert (track["media_type"], track["duration_ms"]) == ("audio/ogg", 2000)
    assert track["license"] == "Apache-2.0" and "ACE-Step" in track["notice"]
    assert track["provenance"]["model_revision"] == MODEL.revision

    # The creator hears it, approves it, and a story can then use it.
    served = await client.get(f"{base}/assets/{track['id']}/content", headers=headers)
    assert served.content == TONE and served.headers["content-type"] == "audio/ogg"
    approved = await client.post(f"{base}/assets/{track['id']}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    story = json.loads((await head(client, headers, base))["story_json"])
    story["assets"]["theme"] = {
        "kind": "music",
        "path": "assets/theme.ogg",
        "sha256": track["sha256"],
    }
    entry = story["entry"]
    story["nodes"]["music_step"] = {"type": "stage", "music": "theme", "next": entry}
    story["entry"] = "music_step"
    saved = await save(client, headers, base, story)
    assert saved.status_code == 201, saved.text
    assert "ACE-Step" in saved.json()["notices"], "The generator is credited in the game"


@pytest.mark.anyio
async def test_a_track_not_yet_approved_cannot_enter_a_story(v2):  # noqa: F811
    client, factory, store, headers, project = v2
    base, _ = await project(schema="2")
    tenant = headers["X-Tenant-ID"]
    configure(narrative_music_generation_enabled=True)
    job = (await request_track(client, headers, base)).json()
    await run_music_job(factory, store, payload_of(tenant, job["id"]))
    track = (await client.get(f"{base}/music-jobs/{job['id']}", headers=headers)).json()["assets"][
        0
    ]
    story = json.loads((await head(client, headers, base))["story_json"])
    story["assets"]["theme"] = {
        "kind": "music",
        "path": "assets/theme.ogg",
        "sha256": track["sha256"],
    }
    entry = story["entry"]
    story["nodes"]["music_step"] = {"type": "stage", "music": "theme", "next": entry}
    story["entry"] = "music_step"
    refused = await save(client, headers, base, story)
    assert refused.status_code == 422
    assert refused.json()["type"].endswith("unknown-asset")


@pytest.mark.anyio
async def test_requests_are_validated_idempotent_and_bounded(v2):  # noqa: F811
    client, _, _, headers, project = v2
    base, _ = await project(schema="2")
    # Off until an operator turns it on.
    refused = await request_track(client, headers, base)
    assert refused.status_code == 409
    assert refused.json()["type"].endswith("music-generation-unavailable")
    listed = (await client.get(f"{base}/music-jobs", headers=headers)).json()
    assert listed["available"] is False and listed["jobs"] == []

    configure(narrative_music_generation_enabled=True)
    assert (await client.get(f"{base}/music-jobs", headers=headers)).json()["available"] is True
    for bad in [
        {"description": "", "seconds": 60},
        {"description": "x" * 501, "seconds": 60},
        {"description": "calm", "seconds": 14},
        {"description": "calm", "seconds": 181},
    ]:
        response = await client.post(
            f"{base}/music-jobs",
            headers=headers,
            json={**bad, "idempotency_key": str(uuid4())},
        )
        assert response.status_code == 422, bad
    blank = await request_track(client, headers, base, description="   ")
    assert blank.status_code == 422

    key = uuid4()
    first = await request_track(client, headers, base, key=key)
    again = await request_track(client, headers, base, key=key)
    assert again.json()["id"] == first.json()["id"], "The same key is the same job"
    conflict = await request_track(client, headers, base, key=key, description="loud drums")
    assert conflict.status_code == 409

    configure(
        narrative_music_generation_enabled=True, narrative_music_max_active_jobs_per_workspace=1
    )
    busy = await request_track(client, headers, base)
    assert busy.status_code == 429


@pytest.mark.anyio
async def test_a_busy_gpu_retries_frees_the_assistant_model_and_fails_safely(v2):  # noqa: F811
    client, factory, store, headers, project = v2
    base, _ = await project(schema="2")
    tenant = headers["X-Tenant-ID"]
    configure(narrative_music_generation_enabled=True)
    job = (await request_track(client, headers, base)).json()
    payload = payload_of(tenant, job["id"])
    run_id = await registered_run(factory, payload)

    # Busy, then free once Ollama unloads: the same attempt succeeds.
    releaser = Releaser()
    outcome = await run_music_job(
        factory, store, payload, FakeMusic("gpu_busy"), releaser=releaser, run_id=run_id
    )
    assert outcome["status"] == "completed" and releaser.calls == 1

    # Still busy with attempts left: Temporal tries again and the job keeps running.
    other = (await request_track(client, headers, base, description="drums")).json()
    payload = payload_of(tenant, other["id"])
    run_id = await registered_run(factory, payload)
    with pytest.raises(ApplicationError, match="gpu_busy"):
        await run_music_job(factory, store, payload, FakeMusic("gpu_busy"), run_id=run_id)
    current = (await client.get(f"{base}/music-jobs/{other['id']}", headers=headers)).json()
    assert current["status"] == "running"

    # Out of attempts: a plain failure code, with nothing to approve.
    outcome = await run_music_job(
        factory, store, payload, FakeMusic("gpu_busy"), attempt=3, run_id=run_id
    )
    assert outcome["status"] == "failed"
    failed = (await client.get(f"{base}/music-jobs/{other['id']}", headers=headers)).json()
    assert failed["error_code"] == "gpu_busy" and failed["assets"] == []


@pytest.mark.anyio
@pytest.mark.parametrize("code", ["generation_failed", "generation_timeout", "invalid_output"])
async def test_other_failures_do_not_retry_and_store_nothing(v2, code):  # noqa: F811
    client, factory, store, headers, project = v2
    base, _ = await project(schema="2")
    tenant = headers["X-Tenant-ID"]
    configure(narrative_music_generation_enabled=True)
    job = (await request_track(client, headers, base)).json()
    before = len(store.objects)
    outcome = await run_music_job(factory, store, payload_of(tenant, job["id"]), FakeMusic(code))
    assert outcome["status"] == "failed"
    assert len(store.objects) == before
    current = (await client.get(f"{base}/music-jobs/{job['id']}", headers=headers)).json()
    assert current["error_code"] == code


@pytest.mark.anyio
async def test_cancelling_a_queued_job_stops_it_and_a_running_one_is_signalled(v2):  # noqa: F811
    client, factory, store, headers, project = v2
    base, _ = await project(schema="2")
    tenant = headers["X-Tenant-ID"]
    configure(narrative_music_generation_enabled=True)
    queued = (await request_track(client, headers, base)).json()
    cancelled = await client.post(f"{base}/music-jobs/{queued['id']}/cancel", headers=headers)
    assert cancelled.json()["status"] == "cancelled"
    generator = FakeMusic()
    outcome = await run_music_job(factory, store, payload_of(tenant, queued["id"]), generator)
    assert outcome["status"] == "stale" and generator.requests == []

    # A cancel during generation wins over the finished track.
    running = (await request_track(client, headers, base, description="drums")).json()

    class CancelsMidway(FakeMusic):
        async def generate(self, request, *, on_progress):
            await client.post(f"{base}/music-jobs/{running['id']}/cancel", headers=headers)
            return await super().generate(request, on_progress=on_progress)

    outcome = await run_music_job(
        factory, store, payload_of(tenant, running["id"]), CancelsMidway()
    )
    assert outcome["status"] == "cancelled"
    final = (await client.get(f"{base}/music-jobs/{running['id']}", headers=headers)).json()
    assert final["assets"] == []
    async with factory() as session:
        topics = list(
            await session.scalars(
                select(OutboxMessage.topic).where(OutboxMessage.aggregate_id == UUID(running["id"]))
            )
        )
    assert MUSIC_CANCELLED_TOPIC in topics


@pytest.mark.anyio
async def test_only_the_registered_run_can_touch_a_job(v2):  # noqa: F811
    client, factory, store, headers, project = v2
    base, _ = await project(schema="2")
    tenant = headers["X-Tenant-ID"]
    configure(narrative_music_generation_enabled=True)
    job = (await request_track(client, headers, base)).json()
    payload = payload_of(tenant, job["id"])
    await registered_run(factory, payload)
    generator = FakeMusic()
    outcome = await run_music_job(factory, store, payload, generator, run_id=uuid4())
    assert outcome["status"] == "stale" and generator.requests == []
    current = (await client.get(f"{base}/music-jobs/{job['id']}", headers=headers)).json()
    assert current["status"] == "queued"


@pytest.mark.anyio
async def test_the_same_bytes_are_one_asset_in_a_project(v2):  # noqa: F811
    client, factory, store, headers, project = v2
    base, _ = await project(schema="2")
    tenant = headers["X-Tenant-ID"]
    configure(narrative_music_generation_enabled=True)
    for description in ("calm piano", "calm strings"):
        job = (await request_track(client, headers, base, description=description)).json()
        await run_music_job(factory, store, payload_of(tenant, job["id"]))
    async with factory() as session:
        count = len(
            list(
                await session.scalars(select(NarrativeAsset).where(NarrativeAsset.kind == "music"))
            )
        )
        jobs = list(await session.scalars(select(NarrativeMusicJob)))
    assert count == 1
    assert {job.status for job in jobs} == {"completed"}


@pytest.mark.anyio
async def test_viewers_can_read_but_not_request(v2):  # noqa: F811
    client, _, _, headers, project = v2
    base, _ = await project(schema="2")
    foreign = await client.get(
        f"{base}/music-jobs", headers={**headers, "X-Tenant-ID": str(uuid4())}
    )
    assert foreign.status_code in (403, 404)


def test_the_music_worker_needs_its_own_queue_and_pinned_paths():
    with pytest.raises(ValueError, match="separate narrative music task queue"):
        Settings(
            env="test",
            narrative_music_worker_enabled=True,
            narrative_music_task_queue="ingestion",
            temporal_task_queue="ingestion",
        )
    with pytest.raises(ValueError, match="pinned model manifest"):
        Settings(env="test", narrative_music_worker_enabled=True)
