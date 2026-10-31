"""Private voice references with a consent declaration (#175, ADR 0044)."""

import hashlib
import math
import struct
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from test_narrative_characters_api import studio  # noqa: F401 - shared fixture
from test_narrative_package_v2_api import configure, head, save, v2  # noqa: F401

from flint_graph.infrastructure.db.models import AuditEvent, NarrativeVoiceReference
from flint_graph.infrastructure.narrative_artifact_store import voice_reference_object_key
from flint_graph.narrative.wav import canonical_wav

CONSENT = {"speaker_name": "Ana Example", "consent": "self", "consent_confirmed": "true"}


def speech(seconds=8.0, amplitude=0.3, rate=24000) -> bytes:
    samples = [
        max(
            -32768,
            min(
                32767,
                round(
                    amplitude
                    * (0.5 + 0.5 * math.sin(2 * math.pi * 3 * i / rate))
                    * math.sin(2 * math.pi * 180 * i / rate)
                    * 32767
                ),
            ),
        )
        for i in range(round(seconds * rate))
    ]
    return canonical_wav(1, rate, struct.pack(f"<{len(samples)}h", *samples))


async def add_reference(client, headers, base, data=None, **form):
    return await client.post(
        f"{base}/voice-references",
        headers=headers,
        data={**CONSENT, "transcript": "The lanterns are lit again.", **form},
        files={"file": ("me.wav", speech() if data is None else data, "audio/wav")},
    )


async def add_member(client, headers, workspace, subject, role):
    added = await client.post(
        f"/v1/workspaces/{workspace['id']}/members",
        headers=headers,
        json={
            "oidc_issuer": "https://keycloak.example/realms/flintgraph",
            "oidc_subject": subject,
            "role": role,
        },
    )
    assert added.status_code == 201


@pytest.mark.anyio
async def test_a_reference_records_who_declared_consent_and_stays_private(studio):  # noqa: F811
    client, factory, store, headers, base, workspace, _ = studio
    created = await add_reference(client, headers, base, name="My voice", source="recording")
    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["name"], body["speaker_name"], body["consent"], body["source"]) == (
        "My voice",
        "Ana Example",
        "self",
        "recording",
    )
    assert body["duration_ms"] == 8000 and body["status"] == "active"
    assert body["transcript"] == "The lanterns are lit again."
    assert body["consent_declared_by_user_id"] and body["consent_declared_at"]
    key = voice_reference_object_key(
        tenant_id=workspace["id"], project_id=base.rsplit("/", 1)[1], reference_id=body["id"]
    )
    assert "/voice-references/" in key and "/assets/" not in key
    assert hashlib.sha256(store.objects[key]).hexdigest() == body["sha256"]

    listed = (await client.get(f"{base}/voice-references", headers=headers)).json()
    assert [item["id"] for item in listed["references"]] == [body["id"]]
    content = await client.get(f"{base}/voice-references/{body['id']}/content", headers=headers)
    assert content.status_code == 200 and content.content == store.objects[key]
    assert content.headers["content-type"] == "audio/wav"
    assert "no-store" in content.headers["cache-control"]
    # References never appear among story assets.
    assets = (await client.get(f"{base}/assets", headers=headers)).json()["assets"]
    assert all(asset["sha256"] != body["sha256"] for asset in assets)

    async with factory() as session:
        events = list(
            await session.scalars(
                select(AuditEvent).where(AuditEvent.resource_type == "narrative_voice_reference")
            )
        )
    assert [event.action.value for event in events] == ["narrative.voice_reference_created"]
    assert "Ana" not in str(events[0].metadata_) and "lanterns" not in str(events[0].metadata_)


@pytest.mark.anyio
async def test_saving_a_reference_requires_a_consent_declaration(studio):  # noqa: F811
    client, _, _, headers, base, *_ = studio
    for form, words in (
        ({"consent_confirmed": "false"}, "permission"),
        ({"consent": "friend"}, "consent"),
        ({"speaker_name": "  "}, "speaker"),
        ({"transcript": "x" * 601}, "transcript"),
    ):
        refused = await add_reference(client, headers, base, **form)
        assert refused.status_code == 422, form
        assert words in refused.text.lower(), form
    permission = await add_reference(client, headers, base, consent="permission")
    assert permission.status_code == 201 and permission.json()["consent"] == "permission"


@pytest.mark.anyio
async def test_unusable_audio_is_refused_with_a_clear_message(studio):  # noqa: F811
    client, _, store, headers, base, *_ = studio
    for data, words in (
        (speech(3), "at least 5 seconds"),
        (speech(31), "at most 30 seconds"),
        (speech(8, amplitude=1.5), "clipped"),
        (speech(8, amplitude=0.002), "barely hear"),
        (b"OggS" + bytes(400), "16-bit pcm wav"),
    ):
        refused = await add_reference(client, headers, base, data=data)
        assert refused.status_code == 422
        assert words in refused.text.lower()
    too_big = await add_reference(client, headers, base, data=bytes(10 * 1024 * 1024 + 1))
    assert too_big.status_code == 413
    assert not store.objects


@pytest.mark.anyio
async def test_only_members_of_the_workspace_reach_references(studio):  # noqa: F811
    client, _, _, headers, base, workspace, oidc_auth = studio
    reference = (await add_reference(client, headers, base)).json()
    await add_member(client, headers, workspace, "reference-viewer", "viewer")
    viewer = {**headers, "Authorization": "Bearer " + oidc_auth("reference-viewer")}
    content = f"{base}/voice-references/{reference['id']}/content"
    assert (await client.get(f"{base}/voice-references", headers=viewer)).status_code == 403
    assert (await client.get(content, headers=viewer)).status_code == 403
    assert (await add_reference(client, viewer, base)).status_code == 403
    deleted = await client.delete(f"{base}/voice-references/{reference['id']}", headers=viewer)
    assert deleted.status_code == 403
    await add_member(client, headers, workspace, "reference-member", "member")
    member = {**headers, "Authorization": "Bearer " + oidc_auth("reference-member")}
    assert (await client.get(content, headers=member)).status_code == 200

    foreign = (await client.post("/v1/workspaces", headers=headers, json={"name": "Other"})).json()
    outside = {**headers, "X-Tenant-ID": foreign["id"]}
    assert (await client.get(content, headers=outside)).status_code == 404
    assert (await client.get(f"{base}/voice-references", headers=outside)).status_code == 404
    other_project = (
        await client.post(
            "/v1/narrative/projects",
            headers=headers,
            json={"name": "Elsewhere", "idempotency_key": str(uuid4())},
        )
    ).json()
    elsewhere = f"/v1/narrative/projects/{other_project['id']}"
    assert (
        await client.get(f"{elsewhere}/voice-references/{reference['id']}/content", headers=headers)
    ).status_code == 404


@pytest.mark.anyio
async def test_deleting_a_reference_removes_its_audio_but_keeps_the_record(studio):  # noqa: F811
    client, factory, store, headers, base, workspace, _ = studio
    reference = (await add_reference(client, headers, base)).json()
    key = voice_reference_object_key(
        tenant_id=workspace["id"], project_id=base.rsplit("/", 1)[1], reference_id=reference["id"]
    )
    deleted = await client.delete(f"{base}/voice-references/{reference['id']}", headers=headers)
    assert deleted.status_code == 200 and deleted.json()["status"] == "deleted"
    assert key not in store.objects
    assert (await client.get(f"{base}/voice-references", headers=headers)).json() == {
        "references": []
    }
    content = await client.get(
        f"{base}/voice-references/{reference['id']}/content", headers=headers
    )
    assert content.status_code == 404
    again = await client.delete(f"{base}/voice-references/{reference['id']}", headers=headers)
    assert again.status_code == 200 and again.json()["status"] == "deleted"
    async with factory() as session:
        row = await session.get(NarrativeVoiceReference, UUID(reference["id"]))
        assert row is not None and row.deleted_at is not None
        assert (row.consent, row.sha256) == ("self", reference["sha256"])
    # Uploading the same sample again makes a new active reference.
    fresh = await add_reference(client, headers, base)
    assert fresh.status_code == 201 and fresh.json()["id"] != reference["id"]
    repeat = await add_reference(client, headers, base)
    assert repeat.status_code == 200 and repeat.json()["id"] == fresh.json()["id"]


@pytest.mark.anyio
async def test_a_story_can_never_bind_reference_audio(v2):  # noqa: F811
    client, _, _, headers, project = v2
    base, _ = await project("Private", schema="2")
    reference = (await add_reference(client, headers, base)).json()
    story = __import__("json").loads((await head(client, headers, base))["story_json"])
    story["assets"]["me"] = {
        "kind": "audio",
        "path": "assets/me.wav",
        "sha256": reference["sha256"],
    }
    refused = await save(client, headers, base, story)
    assert refused.status_code == 422
    assert refused.json()["type"].endswith("unknown-asset")
