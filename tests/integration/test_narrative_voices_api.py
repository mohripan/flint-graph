"""Character voices, voice jobs, voice clip uploads and binding (ADR 0043)."""

import hashlib
import json
import struct
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from temporalio.testing import ActivityEnvironment
from test_narrative_asset_library_api import upload
from test_narrative_package_v2_api import configure, head, save, v2  # noqa: F401

from flint_graph.application.narrative_image_workflow import (
    RUN_VOICE_ACTIVITY,
    VOICE_QUEUED_TOPIC,
    VOICE_WORKFLOW,
    ImageJobPayload,
    voice_job_workflow_id,
)
from flint_graph.application.services.narrative_voices import register_voice_workflow
from flint_graph.infrastructure.db.models import NarrativeVoiceJob, OutboxMessage
from flint_graph.infrastructure.narrative_imagegen import ModelIdentity
from flint_graph.infrastructure.narrative_voicegen import (
    GeneratedClip,
    VoiceGenerationError,
    VoiceResult,
)
from flint_graph.narrative.wav import canonical_wav
from flint_graph.worker.activities.narrative_voice import NarrativeVoiceActivities

MODEL = ModelIdentity("hexgrad/Kokoro-82M", "f" * 40, "apache-2.0")
RUNTIME = {"torch": "2.11.0+cpu", "kokoro": "0.9.4", "misaki": "0.9.4", "device": "cpu"}


class FakeVoices:
    model = MODEL

    def __init__(self, *failures):
        self.failures, self.requests = list(failures), []

    async def generate(self, request, *, on_progress):
        self.requests.append(request)
        if self.failures:
            raise VoiceGenerationError(self.failures.pop(0))
        clips = []
        for index, item in enumerate(request.items):
            frames = 2400 * (index + 1)
            data = canonical_wav(1, 24000, struct.pack("<h", len(item.text)) * frames)
            clips.append(GeneratedClip(index, data, hashlib.sha256(data).hexdigest(), frames))
            await on_progress(index + 1)
        return VoiceResult(clips=tuple(clips), runtime=RUNTIME)


async def run_voice_job(factory, store, payload, generator=None, generators=None):
    run_id = uuid4()
    async with factory() as session:
        await register_voice_workflow(
            session,
            tenant_id=UUID(payload["tenant_id"]),
            job_id=UUID(payload["job_id"]),
            workflow_run_id=run_id,
        )
        await session.commit()
    env = ActivityEnvironment()
    env.info = replace(
        env.info,
        activity_type=RUN_VOICE_ACTIVITY,
        workflow_id=voice_job_workflow_id(payload),
        workflow_type=VOICE_WORKFLOW,
        workflow_run_id=str(run_id),
        attempt=1,
    )
    work = NarrativeVoiceActivities(
        factory=factory,
        generator=generator or FakeVoices(),
        store=store,
        generators=generators or {},
    )
    return await env.run(work.run, payload)


async def choose(client, headers, base, character, voice, version=0):
    return await client.put(
        f"{base}/characters/{character}/voice",
        headers=headers,
        json={"base_version": version, "voice": voice},
    )


def job_body(*items):
    return {"items": list(items), "idempotency_key": str(uuid4())}


@pytest.mark.anyio
async def test_voices_are_chosen_per_character_and_jobs_make_candidate_clips(v2):  # noqa: F811
    client, factory, store, headers, project = v2
    configure(narrative_voice_generation_enabled=True)
    base, _ = await project("Voices", schema="2")
    catalog = (await client.get(f"{base}/voices", headers=headers)).json()
    assert catalog["available"] is True
    ids = [voice["id"] for voice in catalog["voices"]]
    assert "af_heart" in ids and "bm_george" in ids and all(i[0] in "ab" for i in ids)

    line = {"mode": "full", "text": "The lanterns are lit again.", "node_id": "hello"}
    laugh = {"mode": "vocalization", "text": "fufu", "node_id": "laugh"}
    refused = await client.post(
        f"{base}/characters/mira/voice-jobs", headers=headers, json=job_body(line)
    )
    assert refused.status_code == 409 and refused.json()["type"].endswith("voice-not-chosen")
    assert (await choose(client, headers, base, "mira", "zz_nobody")).status_code == 422
    chosen = await choose(client, headers, base, "mira", "bf_emma")
    assert chosen.status_code == 200 and chosen.json()["voice"] == "bf_emma"
    assert (await choose(client, headers, base, "mira", "af_heart")).status_code == 409  # stale
    listed = (await client.get(f"{base}/characters", headers=headers)).json()["profiles"]
    assert listed[0]["voice"] == "bf_emma"

    for bad in (
        {"mode": "vocalization", "text": "f" * 41},
        {"mode": "full", "text": "   "},
        {"mode": "whisper", "text": "hi"},
        {"mode": "full", "text": "hi", "node_id": "Bad Id"},
    ):
        response = await client.post(
            f"{base}/characters/mira/voice-jobs", headers=headers, json=job_body(bad)
        )
        assert response.status_code == 422, bad
    body = job_body(line, laugh)
    queued = await client.post(f"{base}/characters/mira/voice-jobs", headers=headers, json=body)
    assert queued.status_code == 202, queued.text
    job = queued.json()
    assert (job["status"], job["count"], job["voice"]) == ("queued", 2, "bf_emma")
    again = await client.post(f"{base}/characters/mira/voice-jobs", headers=headers, json=body)
    assert again.json()["id"] == job["id"]
    async with factory() as session:
        message = await session.scalar(
            select(OutboxMessage).where(OutboxMessage.aggregate_id == UUID(job["id"]))
        )
        assert message.topic == VOICE_QUEUED_TOPIC
        assert "lantern" not in json.dumps(message.payload)

    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=job["id"]
    )
    generator = FakeVoices()
    outcome = await run_voice_job(factory, store, payload, generator)
    assert outcome == {"job_id": job["id"], "status": "completed"}
    assert [item.mode for item in generator.requests[0].items] == ["full", "vocalization"]
    done = (await client.get(f"{base}/voice-jobs/{job['id']}", headers=headers)).json()
    assert (done["status"], done["progress"], done["model"]) == (
        "completed",
        2,
        f"hexgrad/Kokoro-82M@{'f' * 40}",
    )
    clips = done["assets"]
    assert [clip["kind"] for clip in clips] == ["voice", "voice"]
    assert [clip["status"] for clip in clips] == ["candidate", "candidate"]
    assert clips[0]["name"] == "mira: The lanterns are lit again."
    assert clips[1]["name"] == "mira (fufu)"
    assert (clips[0]["duration_ms"], clips[1]["duration_ms"]) == (100, 200)
    assert clips[1]["provenance"]["mode"] == "vocalization"
    assert clips[1]["provenance"]["node_id"] == "laugh"
    assert clips[0]["provenance"]["voice"] == "bf_emma"
    assert clips[0]["provenance"]["device"] == "cpu"
    assert done["runtime"] == {**RUNTIME, "clip_devices": "cpu,cpu"}
    audio = await client.get(f"{base}/assets/{clips[1]['id']}/content", headers=headers)
    assert audio.headers["content-type"] == "audio/wav" and audio.content[:4] == b"RIFF"
    thumb = await client.get(
        f"{base}/assets/{clips[1]['id']}/content?variant=thumbnail", headers=headers
    )
    assert thumb.status_code == 404
    listed_jobs = (await client.get(f"{base}/voice-jobs", headers=headers)).json()["jobs"]
    assert [item["id"] for item in listed_jobs] == [job["id"]]
    voices = (
        await client.get(f"{base}/assets?kind=voice&character_id=mira", headers=headers)
    ).json()
    assert len(voices["assets"]) == 2

    # Approved clips bind to a story by SHA-256 like images; candidates never do.
    story = json.loads((await head(client, headers, base))["story_json"])
    story["characters"] = {"mira": {"name": "Mira"}}
    story["assets"] = {
        "laugh": {"kind": "audio", "path": "assets/laugh.wav", "sha256": clips[1]["sha256"]}
    }
    entry = story["entry"]
    story["nodes"] = {
        entry: {
            "type": "line",
            "text_id": entry,
            "text": "Or someone never left.",
            "speaker": "mira",
            "voice": {"mode": "vocalization", "text": "fufu", "audio": "laugh"},
            "next": "end",
        },
        "end": {"type": "end", "text_id": "end", "text": "Fin.", "ending": "done"},
    }
    candidate = await save(client, headers, base, story)
    assert candidate.status_code == 422 and candidate.json()["type"].endswith("unknown-asset")
    approved = await client.post(f"{base}/assets/{clips[1]['id']}/approve", headers=headers)
    assert approved.status_code == 200
    saved = await save(client, headers, base, story)
    assert saved.status_code == 201, saved.text
    assert "laugh (audio, sha256" in saved.json()["notices"]
    assert "generated with hexgrad/Kokoro-82M@" in saved.json()["notices"]
    served = await client.get(
        f"{base}/revisions/{saved.json()['id']}/assets/laugh", headers=headers
    )
    assert served.status_code == 200 and served.headers["content-type"] == "audio/wav"


@pytest.mark.anyio
async def test_voice_jobs_fail_safely_and_respect_availability(v2):  # noqa: F811
    client, factory, store, headers, project = v2
    configure(narrative_voice_generation_enabled=False)
    base, _ = await project("Quiet", schema="2")
    assert (await choose(client, headers, base, "quen", "af_bella")).status_code == 200
    line = {"mode": "full", "text": "Hello."}
    closed = await client.post(
        f"{base}/characters/quen/voice-jobs", headers=headers, json=job_body(line)
    )
    assert closed.status_code == 503
    assert (await client.get(f"{base}/voices", headers=headers)).json()["available"] is False
    configure(narrative_voice_generation_enabled=True)
    job = (
        await client.post(
            f"{base}/characters/quen/voice-jobs", headers=headers, json=job_body(line)
        )
    ).json()
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=job["id"]
    )
    outcome = await run_voice_job(factory, store, payload, FakeVoices("empty_speech"))
    assert outcome["status"] == "failed"
    async with factory() as session:
        row = await session.get(NarrativeVoiceJob, UUID(job["id"]))
        assert (row.status, row.error_code, row.execution_token) == ("failed", "empty_speech", None)
    queued = (
        await client.post(
            f"{base}/characters/quen/voice-jobs", headers=headers, json=job_body(line)
        )
    ).json()
    cancelled = await client.post(f"{base}/voice-jobs/{queued['id']}/cancel", headers=headers)
    assert cancelled.json()["status"] == "cancelled"


@pytest.mark.anyio
async def test_voice_clips_upload_as_canonical_wav_with_rights(v2):  # noqa: F811
    client, _, _, headers, project = v2
    base, _ = await project("Uploads", schema="2")
    samples = struct.pack("<4h", 1, -2, 3, -4)
    canonical = canonical_wav(1, 44100, samples)
    noisy = canonical[:36] + b"LIST" + struct.pack("<I", 4) + b"INFO" + canonical[36:]
    noisy = b"RIFF" + struct.pack("<I", len(noisy) - 8) + noisy[8:]
    response = await upload(
        client,
        headers,
        base,
        kind="voice",
        name="Mira laughs",
        data=noisy,
        filename="laugh.wav",
        media="audio/wav",
        form={
            "license": "Own work",
            "notice": "Recorded by the creator.",
            "rights_declared": "true",
            "character_id": "mira",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["kind"], body["media_type"], body["width"], body["duration_ms"]) == (
        "voice",
        "audio/wav",
        None,
        0 or 1,
    )
    assert body["character_id"] == "mira"
    assert body["sha256"] == hashlib.sha256(canonical).hexdigest()
    content = await client.get(f"{base}/assets/{body['id']}/content", headers=headers)
    assert content.content == canonical
    for bad in (b"ID3" + b"\x00" * 40, canonical_wav(1, 24000, samples)[:-2]):
        refused = await upload(
            client,
            headers,
            base,
            kind="voice",
            name="Bad",
            data=bad,
            filename="bad.wav",
            media="audio/wav",
        )
        assert refused.status_code == 422, refused.text
