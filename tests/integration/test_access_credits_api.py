"""Credits: prices, balances, operator adjustments and unlimited access (ADR 0059)."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from test_access_invitations_api import admin_headers, bearer, invite_mode, make_key, problem
from test_narrative_assistant_api import ask, new_thread
from test_narrative_package_v2_api import configure, v2  # noqa: F401
from test_narrative_voice_models_api import choose

from flint_graph.infrastructure.db.models import AccessGrant, CreditLedgerEntry, UsageCharge

pytestmark = pytest.mark.anyio


async def background(client, base, headers, count, key=None):
    return await client.post(
        f"{base}/assets/background-jobs",
        headers=headers,
        json={
            "description": "harbor at dusk",
            "count": count,
            "idempotency_key": key or str(uuid4()),
        },
    )


async def portrait(client, base, headers, count, **flags):
    return await client.post(
        f"{base}/characters/mira/portrait-jobs",
        headers=headers,
        json={
            "appearance": "silver hair, amber eyes, navy coat",
            "character_type": "woman",
            "framing": "full_body",
            "count": count,
            "idempotency_key": str(uuid4()),
            **flags,
        },
    )


async def me(client, headers):
    return (await client.get("/v1/access/me", headers=headers)).json()


async def grant_id(client, admin, email):
    grants = (await client.get("/v1/admin/access/grants", headers=admin)).json()["grants"]
    return next(item for item in grants if item["email"] == email)["id"]


async def change(client, admin, grant, **body):
    return await client.post(f"/v1/admin/access/grants/{grant}/credits", headers=admin, json=body)


async def joined_owner(client, oidc_auth, owner, **invitation):
    """The workspace owner joins with a key carrying ``invitation``; returns its grant."""
    admin = admin_headers(oidc_auth)
    created = await make_key(client, admin, **invitation)
    joined = await client.post("/v1/access/join", headers=owner, json={"key": created["key"]})
    assert joined.status_code == 200, joined.text
    return admin, created, await grant_id(client, admin, "stage-owner@example.com")


async def test_jobs_spend_credits_by_price_and_refuse_when_too_few(v2, oidc_auth):  # noqa: F811
    client, factory, _, owner, project = v2
    base, _ = await project("Credits", schema="2")
    invite_mode(narrative_image_max_active_jobs_per_workspace=50)
    admin, created, grant = await joined_owner(
        client, oidc_auth, owner, credits=30, limits={"image": {"daily": 12}}
    )
    assert (created["invitation"]["credits"], created["invitation"]["unlimited"]) == (30, False)
    status = await me(client, owner)
    assert (status["credits"], status["unlimited"]) == (30, False)
    assert status["prices"]["image.standard"] == {
        "credits": 2,
        "kind": "image",
        "label": "Standard image",
        "unit": "image",
        "per": 1,
    }
    assert status["prices"]["voice.indextts-2.5"]["credits"] == 5

    replay = str(uuid4())
    assert (await background(client, base, owner, 4, replay)).status_code == 202  # 4 × 2
    assert (await background(client, base, owner, 4, replay)).status_code == 202  # free replay
    assert (await me(client, owner))["credits"] == 22
    assert (await portrait(client, base, owner, 2, transparent=True, hires=True)).status_code == 202
    assert (await me(client, owner))["credits"] == 12  # 2 × 5
    assert (await portrait(client, base, owner, 4, transparent=True)).status_code == 202
    assert (await me(client, owner))["credits"] == 0  # 4 × 3

    async with factory() as session:
        charges = await session.scalar(select(func.count(UsageCharge.id)))
    out = await background(client, base, owner, 1)
    assert out.status_code == 402 and problem(out) == "out-of-credits"
    assert out.json()["detail"].startswith(
        "Standard image costs 2 credits, but you have none left."
    )
    assert out.json()["errors"] == [{"credits_needed": 2, "credits_left": 0}]
    async with factory() as session:
        assert await session.scalar(select(func.count(UsageCharge.id))) == charges

    history = (await client.get("/v1/access/credits", headers=owner)).json()["entries"]
    assert [
        (e["change"], e["amount"], e["balance"], e["item"], e["quantity"]) for e in history
    ] == [
        ("charge", -12, 0, "image.sprite", 4),
        ("charge", -10, 12, "image.high_res", 2),
        ("charge", -8, 22, "image.standard", 4),
        ("join", 30, 30, None, None),
    ]
    assert history[0]["subject"].startswith("image_job:")

    # Operators top up, take away and set credits, with a note for the record.
    guest = bearer(oidc_auth, "guest")
    assert (await change(client, guest, grant, change="add", amount=5)).status_code == 403
    topped = await change(client, admin, grant, change="add", amount=100, note="Pilot week")
    assert topped.status_code == 200 and topped.json()["credits"] == 100
    # The cap still applies: 10 images today, 3 more would pass 12. No credits are spent.
    capped = await background(client, base, owner, 3)
    assert capped.status_code == 429 and problem(capped) == "usage-limit"
    assert "images" in capped.json()["detail"]
    assert (await me(client, owner))["credits"] == 100
    too_many = await change(client, admin, grant, change="remove", amount=101)
    assert too_many.status_code == 422 and "100" in too_many.json()["detail"]
    removed = await change(client, admin, grant, change="remove", amount=40, note="Over-granted")
    assert removed.json()["credits"] == 60
    assert (await change(client, admin, grant, change="set", amount=0)).json()["credits"] == 0
    assert (await change(client, admin, grant, change="add", amount=0)).status_code == 422
    audit = (await client.get(f"/v1/admin/access/grants/{grant}/credits", headers=admin)).json()[
        "entries"
    ]
    assert [(e["change"], e["amount"], e["balance"], e["note"]) for e in audit[:3]] == [
        ("set", -60, 0, None),
        ("remove", -40, 60, "Over-granted"),
        ("add", 100, 100, "Pilot week"),
    ]
    assert audit[0]["actor_email"] == "boss@example.com"
    assert (
        await client.get(f"/v1/admin/access/grants/{grant}/credits", headers=guest)
    ).status_code == 403


async def test_an_unlimited_key_spends_nothing_until_an_operator_limits_it(v2, oidc_auth):  # noqa: F811
    client, factory, _, owner, project = v2
    base, _ = await project("Unlimited", schema="2")
    invite_mode(narrative_image_max_active_jobs_per_workspace=50)
    admin, created, grant = await joined_owner(
        client, oidc_auth, owner, unlimited=True, credits=50, limits={"image": {"daily": 1}}
    )
    # An unlimited invitation carries no credits and no caps, so turning it off fails closed.
    invitation = created["invitation"]
    assert (invitation["unlimited"], invitation["credits"], invitation["limits"]) == (True, 0, {})
    assert (await me(client, owner))["unlimited"] is True
    for _ in range(3):
        assert (await background(client, base, owner, 4)).status_code == 202
    status = await me(client, owner)
    assert status["credits"] == 0 and status["usage"]["image"]["total"] == 12
    async with factory() as session:
        entries = (await session.scalars(select(CreditLedgerEntry.change))).all()
    assert entries == ["join"]

    limited = await client.post(
        f"/v1/admin/access/grants/{grant}/unlimited",
        headers=admin,
        json={"unlimited": False, "note": "Trial over"},
    )
    assert limited.status_code == 200 and limited.json()["unlimited"] is False
    assert (await background(client, base, owner, 1)).status_code == 402
    again = await client.post(
        f"/v1/admin/access/grants/{grant}/unlimited", headers=admin, json={"unlimited": True}
    )
    assert again.json()["unlimited"] is True
    assert (await background(client, base, owner, 1)).status_code == 202
    audit = (await client.get(f"/v1/admin/access/grants/{grant}/credits", headers=admin)).json()[
        "entries"
    ]
    assert [(e["change"], e["amount"], e["note"]) for e in audit] == [
        ("unlimited", 0, None),
        ("limited", 0, "Trial over"),
        ("join", 0, None),
    ]

    # Operators are unlimited without any grant; open mode charges nobody.
    assert (await me(client, admin))["unlimited"] is True
    # An operator's balance is their own (ADR 0074); it is not a grant.
    assert (await me(client, admin))["keeps_going"] is True


async def test_defaults_overrides_older_grants_voices_and_the_assistant(v2, oidc_auth):  # noqa: F811
    client, factory, _, owner, project = v2
    base, created_project = await project("Defaults", schema="2")
    invite_mode(
        narrative_image_max_active_jobs_per_workspace=50,
        narrative_voice_generation_enabled=True,
        narrative_assistant_provider="deterministic",
        access_default_credits=20,
        access_credit_prices={"image.standard": 3},
    )
    admin, created, grant = await joined_owner(client, oidc_auth, owner)
    assert created["invitation"]["credits"] == 20
    listed = (await client.get("/v1/admin/access/invitations", headers=admin)).json()
    assert listed["default_credits"] == 20
    status = await me(client, owner)
    assert status["prices"]["image.standard"]["credits"] == 3
    # The Studio prices an assistant turn by the provider this server runs.
    assert status["assistant_item"] == "assistant.deterministic"
    assert (await background(client, base, owner, 2)).status_code == 202
    assert (await me(client, owner))["credits"] == 14  # the override, 2 × 3

    # Voice lines are priced by the character's model.
    assert (await choose(client, owner, base, "mira", voice="bf_emma")).status_code == 200
    lines = [
        {"mode": "full", "text": "The lanterns are lit again.", "node_id": "a"},
        {"mode": "full", "text": "Come home.", "node_id": "b"},
    ]
    spoken = await client.post(
        f"{base}/characters/mira/voice-jobs",
        headers=owner,
        json={"items": lines, "idempotency_key": str(uuid4())},
    )
    assert spoken.status_code == 202, spoken.text
    # The assistant is priced by the server's provider.
    thread = await new_thread(client, owner, base)
    asked = await ask(client, owner, base, thread, created_project["head_revision_id"])
    assert asked.status_code == 202, asked.text
    history = (await client.get("/v1/access/credits", headers=owner)).json()["entries"]
    assert [(e["item"], e["quantity"], e["amount"]) for e in history[:2]] == [
        ("assistant.deterministic", 1, -1),
        ("voice.kokoro-82m", 2, -2),
    ]
    assert (await me(client, owner))["credits"] == 11

    # Grants from before credits have no balance: caps only, until an operator sets one.
    async with factory() as session:
        await session.execute(
            update(AccessGrant).where(AccessGrant.id == UUID(grant)).values(credits=None)
        )
        await session.commit()
    assert (await background(client, base, owner, 2)).status_code == 202
    assert (await me(client, owner))["credits"] is None
    refused = await change(client, admin, grant, change="add", amount=5)
    assert refused.status_code == 409 and problem(refused) == "credits-not-set"
    assert (await change(client, admin, grant, change="set", amount=9)).json()["credits"] == 9
