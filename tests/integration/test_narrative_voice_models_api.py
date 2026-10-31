"""Voice model catalog, license acceptance and cloned voices (#176, #177, #178, ADR 0045)."""

import hashlib
import json
import struct
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from test_narrative_characters_api import studio  # noqa: F401 - shared fixture
from test_narrative_package_v2_api import configure, head, save, v2  # noqa: F401
from test_narrative_voice_references_api import add_member, add_reference
from test_narrative_voices_api import job_body, run_voice_job

from flint_graph.application.narrative_image_workflow import ImageJobPayload
from flint_graph.config import NarrativeVoiceModelInstall
from flint_graph.infrastructure.db.models import (
    NarrativeVoiceJob,
    NarrativeVoiceLicenseAcceptance,
)
from flint_graph.infrastructure.narrative_imagegen import ModelIdentity
from flint_graph.infrastructure.narrative_voicegen import GeneratedClip, VoiceResult
from flint_graph.narrative.player_terms import NOTICE_MARKER, player_terms
from flint_graph.narrative.voice_models import LICENSES, MODELS
from flint_graph.narrative.wav import canonical_wav

INSTALL = NarrativeVoiceModelInstall(
    model_dir="C:/models/x", manifest_sha256="a" * 64, runtime_dir="C:/runtimes/x"
)
BILIBILI = LICENSES["bilibili-model-use"]


def install(*models: str) -> None:
    configure(
        narrative_voice_generation_enabled=True,
        narrative_voice_models={model_id: INSTALL for model_id in models},
    )


class FakeEngine:
    """Stands in for one catalog model's child; records what reached it."""

    def __init__(self, model_id: str, rate: int = 24000):
        spec = MODELS[model_id]
        self.model = ModelIdentity(spec.repo, spec.revision, spec.license_id)
        self.rate, self.requests = rate, []

    async def generate(self, request, *, on_progress):
        self.requests.append(request)
        clips = []
        for index, item in enumerate(request.items):
            frames = self.rate // 10 * (index + 1)
            data = canonical_wav(1, self.rate, struct.pack("<h", len(item.text) + 7) * frames)
            clips.append(
                GeneratedClip(
                    index, data, hashlib.sha256(data).hexdigest(), frames, "cuda", self.rate
                )
            )
            await on_progress(index + 1)
        runtime = {"torch": "2.8.0+cu128", "engine": "fake", "device": "fake GPU"}
        return VoiceResult(clips=tuple(clips), runtime=runtime)


async def choose(client, headers, base, character, version=0, **voice):
    return await client.put(
        f"{base}/characters/{character}/voice",
        headers=headers,
        json={"base_version": version, "voice": None, **voice},
    )


async def accept(client, headers, model_id, sha256=BILIBILI.sha256):
    return await client.post(
        f"/v1/narrative/voice-models/{model_id}/license-acceptance",
        headers=headers,
        json={"license_sha256": sha256},
    )


def line(text="You promised me.", node="l1", **delivery):
    item = {"mode": "full", "text": text, "node_id": node}
    return {**item, "delivery": delivery} if delivery else item


@pytest.mark.anyio
async def test_the_catalog_offers_only_installed_models_with_their_licenses(studio):  # noqa: F811
    client, _, _, headers, base, *_ = studio
    install()
    catalog = (await client.get(f"{base}/voices", headers=headers)).json()
    assert [model["id"] for model in catalog["models"]] == ["kokoro-82m"]
    kokoro = catalog["models"][0]
    assert kokoro["default"] is True and kokoro["cloning"] is False
    assert kokoro["license"]["obligations"] == "none" and kokoro["accepted"] is True
    assert kokoro["deliveries"] == {"neutral": "full"}
    assert any(voice["id"] == "af_heart" for voice in kokoro["stock_voices"])

    install("chatterbox-turbo", "qwen3-tts-voices", "indextts-2.5")
    catalog = (await client.get(f"{base}/voices", headers=headers)).json()
    models = {model["id"]: model for model in catalog["models"]}
    assert list(models) == ["kokoro-82m", "chatterbox-turbo", "qwen3-tts-voices", "indextts-2.5"]
    assert models["chatterbox-turbo"]["tags"][:2] == ["laugh", "chuckle"]
    assert models["chatterbox-turbo"]["watermark"] == "perth"
    assert models["qwen3-tts-voices"]["deliveries"]["whisper"] == "full"
    assert {voice["id"] for voice in models["qwen3-tts-voices"]["stock_voices"]} >= {"Ono_Anna"}
    index = models["indextts-2.5"]
    assert index["license"] == {
        "id": "bilibili-model-use",
        "name": BILIBILI.name,
        "sha256": BILIBILI.sha256,
        "obligations": "player_terms",
        "summary": BILIBILI.summary,
    }
    assert index["accepted"] is False and index["cloning"] is True

    text = await client.get("/v1/narrative/voice-licenses/bilibili-model-use", headers=headers)
    assert text.status_code == 200
    body = text.json()
    assert body["text"] == BILIBILI.text and body["sha256"] == BILIBILI.sha256
    assert body["player_terms"] == BILIBILI.player_terms
    unknown = await client.get("/v1/narrative/voice-licenses/cc-by-nc-4.0", headers=headers)
    assert unknown.status_code == 404


@pytest.mark.anyio
async def test_characters_choose_a_model_with_a_stock_voice_or_a_reference(studio):  # noqa: F811
    client, _, _, headers, base, *_ = studio
    install("chatterbox", "qwen3-tts-voices")
    reference = (await add_reference(client, headers, base)).json()

    kokoro = await choose(client, headers, base, "mira", voice="af_heart")
    assert kokoro.status_code == 200, kokoro.text
    assert (kokoro.json()["voice"], kokoro.json()["voice_model"]) == ("af_heart", "kokoro-82m")
    cloned = await choose(
        client, headers, base, "mira", 1, model="chatterbox", reference_id=reference["id"]
    )
    assert cloned.status_code == 200, cloned.text
    profile = cloned.json()
    assert (profile["voice"], profile["voice_model"], profile["voice_reference_id"]) == (
        None,
        "chatterbox",
        reference["id"],
    )
    stock = await choose(client, headers, base, "quen", model="qwen3-tts-voices", voice="Ono_Anna")
    assert stock.status_code == 200 and stock.json()["voice"] == "Ono_Anna"

    for bad, code in (
        ({"model": "chatterbox", "voice": "af_heart"}, 422),  # Chatterbox has no stock voices
        ({"model": "qwen3-tts-voices", "reference_id": reference["id"]}, 422),  # cannot clone
        ({"model": "qwen3-tts-voices", "voice": "Nobody"}, 422),
        ({"model": "indextts-2.5", "reference_id": reference["id"]}, 422),  # not installed
        ({"model": "xtts-v2", "voice": "x"}, 422),
        ({"model": "chatterbox", "reference_id": str(uuid4())}, 404),
        ({"voice": "af_heart", "reference_id": reference["id"]}, 422),
    ):
        response = await choose(client, headers, base, "quen", 1, **bad)
        assert response.status_code == code, (bad, response.text)
    cleared = await choose(client, headers, base, "quen", 1)
    assert cleared.status_code == 200
    assert (cleared.json()["voice"], cleared.json()["voice_model"]) == (None, None)


@pytest.mark.anyio
async def test_generation_with_an_obligating_license_waits_for_acceptance(studio):  # noqa: F811
    client, factory, _, headers, base, workspace, oidc_auth = studio
    install("indextts-2.5")
    reference = (await add_reference(client, headers, base)).json()
    chosen = await choose(
        client, headers, base, "mira", model="indextts-2.5", reference_id=reference["id"]
    )
    assert chosen.status_code == 200
    refused = await client.post(
        f"{base}/characters/mira/voice-jobs", headers=headers, json=job_body(line())
    )
    assert refused.status_code == 409
    assert refused.json()["type"].endswith("voice-license-not-accepted")
    async with factory() as session:
        assert not list(await session.scalars(select(NarrativeVoiceJob)))

    stale = await accept(client, headers, "indextts-2.5", sha256="0" * 64)
    assert stale.status_code == 409 and stale.json()["type"].endswith("voice-license-changed")
    assert (await accept(client, headers, "chatterbox")).status_code == 404  # not installed
    accepted = await accept(client, headers, "indextts-2.5")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["license_sha256"] == BILIBILI.sha256
    assert (await accept(client, headers, "indextts-2.5")).status_code == 200  # idempotent
    catalog = (await client.get(f"{base}/voices", headers=headers)).json()
    assert next(m for m in catalog["models"] if m["id"] == "indextts-2.5")["accepted"] is True
    queued = await client.post(
        f"{base}/characters/mira/voice-jobs", headers=headers, json=job_body(line())
    )
    assert queued.status_code == 202, queued.text

    # Another member of the same workspace accepts for themselves.
    await add_member(client, headers, workspace, "voice-member", "member")
    member = {**headers, "Authorization": "Bearer " + oidc_auth("voice-member")}
    theirs = await client.post(
        f"{base}/characters/mira/voice-jobs", headers=member, json=job_body(line())
    )
    assert theirs.status_code == 409
    # Acceptance in one workspace does not carry to another.
    other = (await client.post("/v1/workspaces", headers=headers, json={"name": "Other"})).json()
    elsewhere = {**headers, "X-Tenant-ID": other["id"]}
    project = (
        await client.post(
            "/v1/narrative/projects",
            headers=elsewhere,
            json={"name": "Elsewhere", "idempotency_key": str(uuid4())},
        )
    ).json()
    other_base = f"/v1/narrative/projects/{project['id']}"
    other_reference = (await add_reference(client, elsewhere, other_base)).json()
    await choose(
        client,
        elsewhere,
        other_base,
        "mira",
        model="indextts-2.5",
        reference_id=other_reference["id"],
    )
    refused_elsewhere = await client.post(
        f"{other_base}/characters/mira/voice-jobs", headers=elsewhere, json=job_body(line())
    )
    assert refused_elsewhere.status_code == 409
    async with factory() as session:
        rows = list(await session.scalars(select(NarrativeVoiceLicenseAcceptance)))
    assert [(str(row.tenant_id), row.model_id, row.license_sha256) for row in rows] == [
        (workspace["id"], "indextts-2.5", BILIBILI.sha256)
    ]


@pytest.mark.anyio
async def test_a_changed_license_text_asks_again(studio):  # noqa: F811
    client, factory, _, headers, base, workspace, _ = studio
    install("indextts-2.5")
    reference = (await add_reference(client, headers, base)).json()
    await choose(client, headers, base, "mira", model="indextts-2.5", reference_id=reference["id"])
    async with factory() as session:
        session.add(
            NarrativeVoiceLicenseAcceptance(
                tenant_id=UUID(workspace["id"]),
                user_id=UUID(reference["consent_declared_by_user_id"]),
                model_id="indextts-2.5",
                license_id="bilibili-model-use",
                license_sha256="b" * 64,  # an earlier text
            )
        )
        await session.commit()
    refused = await client.post(
        f"{base}/characters/mira/voice-jobs", headers=headers, json=job_body(line())
    )
    assert refused.status_code == 409


@pytest.mark.anyio
async def test_cloned_clips_record_model_reference_consent_and_delivery(studio):  # noqa: F811
    client, factory, store, headers, base, *_ = studio
    install("chatterbox", "chatterbox-turbo", "indextts-2.5")
    reference = (await add_reference(client, headers, base, consent="permission")).json()
    await choose(client, headers, base, "mira", model="chatterbox", reference_id=reference["id"])
    whisper = await client.post(
        f"{base}/characters/mira/voice-jobs",
        headers=headers,
        json=job_body(line(emotion="whisper", intensity=0.5)),
    )
    assert whisper.status_code == 422 and "cannot speak a line whisper" in whisper.text
    job = (
        await client.post(
            f"{base}/characters/mira/voice-jobs",
            headers=headers,
            json={
                **job_body(
                    line("You promised me!", "l1", emotion="angry", intensity=0.8),
                    {"mode": "vocalization", "text": "hmph", "node_id": "l2"},
                ),
                "language": "en",
            },
        )
    ).json()
    assert (job["voice_model"], job["voice"], job["reference_id"]) == (
        "chatterbox",
        None,
        reference["id"],
    )
    assert job["items"][0]["delivery"] == {"emotion": "angry", "intensity": 0.8, "tag": None}
    assert job["items"][1]["delivery"] == {"emotion": "neutral", "intensity": 0.5, "tag": None}
    async with factory() as session:
        row = await session.get(NarrativeVoiceJob, UUID(job["id"]))
        assert row.reference_sha256 == reference["sha256"]
        assert row.consent["consent"] == "permission"
        assert row.consent["speaker_name"] == "Ana Example"
        assert row.consent["declared_by_user_id"] == reference["consent_declared_by_user_id"]

    engine = FakeEngine("chatterbox")
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=job["id"]
    )
    outcome = await run_voice_job(factory, store, payload, generators={"chatterbox": engine})
    assert outcome["status"] == "completed"
    request = engine.requests[0]
    assert request.model == "chatterbox" and request.voice is None
    assert request.reference.sha256 == reference["sha256"]
    assert hashlib.sha256(request.reference.data).hexdigest() == reference["sha256"]
    assert request.reference.transcript == "The lanterns are lit again."
    assert request.items[0].delivery.emotion == "angry"
    done = (await client.get(f"{base}/voice-jobs/{job['id']}", headers=headers)).json()
    clip = done["assets"][0]
    made = clip["provenance"]
    assert made["generator"] == "local-chatterbox" and made["model_id"] == "chatterbox"
    assert made["license"] == {
        "id": "chatterbox-mit",
        "name": LICENSES["chatterbox-mit"].name,
        "sha256": LICENSES["chatterbox-mit"].sha256,
        "obligations": "none",
    }
    assert made["reference"] == {
        "id": reference["id"],
        "sha256": reference["sha256"],
        "consent": "permission",
        "speaker_name": "Ana Example",
        "declared_by_user_id": reference["consent_declared_by_user_id"],
        "declared_at": made["reference"]["declared_at"],
    }
    assert made["watermark"] == "perth" and made["delivery"]["emotion"] == "angry"
    assert made["language"] == "en" and made["device"] == "cuda"
    assert clip["license"] == LICENSES["chatterbox-mit"].name and not clip["notice"]

    # IndexTTS clips name the agreement and carry bilibili's notice.
    await client.post(
        "/v1/narrative/voice-models/indextts-2.5/license-acceptance",
        headers=headers,
        json={"license_sha256": BILIBILI.sha256},
    )
    me = (await client.get(f"{base}/characters", headers=headers)).json()["profiles"][0]
    await choose(
        client,
        headers,
        base,
        "mira",
        me["version"],
        model="indextts-2.5",
        reference_id=reference["id"],
    )
    index_job = (
        await client.post(
            f"{base}/characters/mira/voice-jobs",
            headers=headers,
            json=job_body(line("Run!", "l3", emotion="afraid", intensity=1)),
        )
    ).json()
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=index_job["id"]
    )
    index_engine = FakeEngine("indextts-2.5", rate=22050)
    await run_voice_job(factory, store, payload, generators={"indextts-2.5": index_engine})
    index_clip = (await client.get(f"{base}/voice-jobs/{index_job['id']}", headers=headers)).json()
    asset = index_clip["assets"][0]
    assert asset["license"] == BILIBILI.name and asset["notice"] == BILIBILI.notice
    assert asset["provenance"]["license"]["obligations"] == "player_terms"
    assert asset["provenance"]["watermark"] is None
    assert asset["duration_ms"] == 100


@pytest.mark.anyio
async def test_deleting_a_reference_blocks_new_and_queued_jobs(studio):  # noqa: F811
    client, factory, store, headers, base, *_ = studio
    install("chatterbox")
    reference = (await add_reference(client, headers, base)).json()
    await choose(client, headers, base, "mira", model="chatterbox", reference_id=reference["id"])
    queued = (
        await client.post(
            f"{base}/characters/mira/voice-jobs", headers=headers, json=job_body(line())
        )
    ).json()
    await client.delete(f"{base}/voice-references/{reference['id']}", headers=headers)
    refused = await client.post(
        f"{base}/characters/mira/voice-jobs", headers=headers, json=job_body(line())
    )
    assert refused.status_code == 409 and refused.json()["type"].endswith("voice-reference-deleted")
    payload = ImageJobPayload(
        schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=queued["id"]
    )
    engine = FakeEngine("chatterbox")
    outcome = await run_voice_job(factory, store, payload, generators={"chatterbox": engine})
    assert outcome["status"] == "stale" and not engine.requests  # closed at claim
    async with factory() as session:
        row = await session.get(NarrativeVoiceJob, UUID(queued["id"]))
        assert (row.status, row.error_code) == ("failed", "reference_deleted")


@pytest.mark.anyio
async def test_line_delivery_is_editor_metadata(studio):  # noqa: F811
    client, _, _, headers, base, workspace, oidc_auth = studio
    empty = await client.get(f"{base}/line-deliveries", headers=headers)
    assert empty.status_code == 200 and empty.json() == {"deliveries": []}
    saved = await client.put(
        f"{base}/line-deliveries/l1",
        headers=headers,
        json={"emotion": "dramatic", "intensity": 0.75, "tag": None},
    )
    assert saved.status_code == 200, saved.text
    changed = await client.put(
        f"{base}/line-deliveries/l1",
        headers=headers,
        json={"emotion": "sad", "intensity": 0.25, "tag": "sigh"},
    )
    assert changed.json() == {"node_id": "l1", "emotion": "sad", "intensity": 0.25, "tag": "sigh"}
    listed = (await client.get(f"{base}/line-deliveries", headers=headers)).json()
    assert listed["deliveries"] == [changed.json()]
    for bad in ({"emotion": "sarcastic"}, {"emotion": "sad", "intensity": 2}, {"tag": "x" * 40}):
        response = await client.put(f"{base}/line-deliveries/l1", headers=headers, json=bad)
        assert response.status_code == 422, bad
    assert (await client.delete(f"{base}/line-deliveries/l1", headers=headers)).status_code == 204
    assert (await client.get(f"{base}/line-deliveries", headers=headers)).json() == {
        "deliveries": []
    }
    await add_member(client, headers, workspace, "delivery-viewer", "viewer")
    viewer = {**headers, "Authorization": "Bearer " + oidc_auth("delivery-viewer")}
    assert (await client.get(f"{base}/line-deliveries", headers=viewer)).status_code == 200
    denied = await client.put(
        f"{base}/line-deliveries/l1", headers=viewer, json={"emotion": "sad", "intensity": 0.5}
    )
    assert denied.status_code == 403


@pytest.mark.anyio
async def test_releases_carry_license_duties_only_for_clips_that_need_them(v2):  # noqa: F811
    client, factory, store, headers, project = v2
    install("chatterbox", "indextts-2.5")
    base, _ = await project("Licensed", schema="2")
    reference = (await add_reference(client, headers, base)).json()

    async def clips(model_id, rate, *texts):
        profiles = (await client.get(f"{base}/characters", headers=headers)).json()["profiles"]
        version = next((p["version"] for p in profiles if p["character_id"] == "mira"), 0)
        await choose(
            client, headers, base, "mira", version, model=model_id, reference_id=reference["id"]
        )
        job = (
            await client.post(
                f"{base}/characters/mira/voice-jobs",
                headers=headers,
                json=job_body(*(line(text, f"n{index}") for index, text in enumerate(texts))),
            )
        ).json()
        payload = ImageJobPayload(
            schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=job["id"]
        )
        engine = FakeEngine(model_id, rate)
        await run_voice_job(factory, store, payload, generators={model_id: engine})
        done = (await client.get(f"{base}/voice-jobs/{job['id']}", headers=headers)).json()
        for asset in done["assets"]:
            await client.post(f"{base}/assets/{asset['id']}/approve", headers=headers)
        return done["assets"]

    calm = await clips("chatterbox", 24000, "The tide is turning.")
    await accept(client, headers, "indextts-2.5")
    cry = await clips("indextts-2.5", 22050, "Run!")

    def story_with(*bound):
        story = json.loads(revision["story_json"])
        story["characters"] = {"mira": {"name": "Mira"}}
        story["assets"] = {
            key: {"kind": "audio", "path": f"assets/{key}.wav", "sha256": asset["sha256"]}
            for key, asset in bound
        }
        nodes, entry = {}, story["entry"]
        ids = [entry] + [f"line{index}" for index in range(1, len(bound))] + ["end"]
        for index, (key, _) in enumerate(bound):
            nodes[ids[index]] = {
                "type": "line",
                "text_id": ids[index],
                "text": key,
                "speaker": "mira",
                "voice": {"mode": "full", "audio": key},
                "next": ids[index + 1],
            }
        nodes["end"] = {"type": "end", "text_id": "end", "text": "Fin.", "ending": "done"}
        story["nodes"] = nodes
        return story

    revision = await head(client, headers, base)
    quiet = await save(client, headers, base, story_with(("calm", calm[0])), "By me.")
    assert quiet.status_code == 201, quiet.text
    assert player_terms(quiet.json()["notices"]) is None
    assert BILIBILI.text not in quiet.json()["notices"]
    listed = (
        await client.get(f"{base}/revisions/{quiet.json()['id']}/voice-licenses", headers=headers)
    ).json()
    assert listed["player_terms"] is False
    assert [(item["id"], item["obligations"]) for item in listed["licenses"]] == [
        ("chatterbox-mit", "none")
    ]

    revision = await head(client, headers, base)
    loud = await save(
        client, headers, base, story_with(("calm", calm[0]), ("cry", cry[0])), "By me."
    )
    assert loud.status_code == 201, loud.text
    notices = loud.json()["notices"]
    terms = player_terms(notices)
    assert terms is not None and terms.startswith(BILIBILI.player_terms)
    assert "  " + BILIBILI.notice in notices
    listed = (
        await client.get(f"{base}/revisions/{loud.json()['id']}/voice-licenses", headers=headers)
    ).json()
    assert listed["player_terms"] is True
    bilibili = next(item for item in listed["licenses"] if item["id"] == "bilibili-model-use")
    assert bilibili["lines"] == [{"node_id": "line1", "asset": "cry"}]
    assert bilibili["obligations"] == "player_terms"
    # A creator cannot strip the duties: the server recomposes the generated part.
    revision = await head(client, headers, base)
    stripped = await save(
        client,
        headers,
        base,
        story_with(("calm", calm[0]), ("cry", cry[0])),
        notices.split(NOTICE_MARKER)[0],
    )
    assert player_terms(stripped.json()["notices"]) == terms
