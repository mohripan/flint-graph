"""Invite-only access: keys, email invitations, grants and usage limits (ADR 0058)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from test_narrative_package_v2_api import configure, v2  # noqa: F401

from conftest import OIDC_ISSUER
from flint_graph.infrastructure.db.models import AccessInvitation, UsageCharge

pytestmark = pytest.mark.anyio
ADMIN = "boss@example.com"


def bearer(oidc_auth, subject, **claims):
    return {"Authorization": "Bearer " + oidc_auth(subject, **claims)}


def admin_headers(oidc_auth):
    return bearer(oidc_auth, "boss", email=ADMIN, email_verified=True)


def invite_mode(**changes):
    configure(access_mode="invite", access_admin_emails=[ADMIN], **changes)


async def make_key(client, admin, **body):
    response = await client.post(
        "/v1/admin/access/invitations",
        headers=admin,
        json={"kind": "key", "label": "ACME demo", **body},
    )
    assert response.status_code == 201, response.text
    return response.json()


def problem(response) -> str:
    return response.json()["type"].rsplit(":", 1)[-1]


async def test_invite_mode_needs_an_invitation_and_a_key_works_once(v2, oidc_auth):  # noqa: F811
    client, *_ = v2
    invite_mode()
    admin, guest = admin_headers(oidc_auth), bearer(oidc_auth, "guest")

    response = await client.get("/v1/workspaces", headers=guest)
    assert response.status_code == 403 and problem(response) == "access-required"
    me = (await client.get("/v1/access/me", headers=guest)).json()
    assert (me["mode"], me["has_access"], me["is_admin"]) == ("invite", False, False)
    me = (await client.get("/v1/access/me", headers=admin)).json()
    assert me["has_access"] and me["is_admin"]
    assert (await client.get("/v1/workspaces", headers=admin)).status_code == 200

    refused = await client.post(
        "/v1/admin/access/invitations", headers=guest, json={"kind": "key", "label": "x"}
    )
    assert refused.status_code == 403
    created = await make_key(client, admin, limits={"image": {"daily": 3}})
    key = created["key"]
    assert created["invitation"]["key_hint"] == key[-4:]
    assert created["invitation"]["max_redemptions"] == 1
    listed = (await client.get("/v1/admin/access/invitations", headers=admin)).json()
    assert key not in str(listed) and listed["invitations"][0]["label"] == "ACME demo"

    wrong = await client.post(
        "/v1/access/join", headers=guest, json={"key": "FG-AAAA-AAAA-AAAA-AAAA"}
    )
    assert wrong.status_code == 404 and problem(wrong) == "invitation-invalid"
    joined = await client.post(
        "/v1/access/join", headers=guest, json={"key": key.lower().replace("-", " ")}
    )
    assert joined.status_code == 200, joined.text
    assert joined.json()["has_access"] and joined.json()["limits"] == {"image": {"daily": 3}}
    assert (await client.get("/v1/workspaces", headers=guest)).status_code == 200
    # Joining again is harmless; the key is now used up for anyone else.
    assert (
        await client.post("/v1/access/join", headers=guest, json={"key": key})
    ).status_code == 200
    late = await client.post(
        "/v1/access/join", headers=bearer(oidc_auth, "other"), json={"key": key}
    )
    assert late.status_code == 404 and problem(late) == "invitation-invalid"


async def test_email_invitations_need_the_verified_address(v2, oidc_auth):  # noqa: F811
    client, *_ = v2
    invite_mode()
    admin = admin_headers(oidc_auth)
    created = await client.post(
        "/v1/admin/access/invitations",
        headers=admin,
        json={"kind": "email", "label": "Ana at Studio", "email": " Ana@Studio.Example "},
    )
    assert created.status_code == 201, created.text
    assert created.json()["key"] is None
    assert created.json()["invitation"]["email"] == "ana@studio.example"

    unverified = bearer(oidc_auth, "ana-1", email="ana@studio.example")
    assert (await client.get("/v1/access/me", headers=unverified)).json()[
        "email_invitation"
    ] is False
    refused = await client.post("/v1/access/join", headers=unverified, json={})
    assert refused.status_code == 404 and problem(refused) == "invitation-invalid"

    verified = bearer(oidc_auth, "ana-2", email="ANA@studio.example", email_verified=True)
    assert (await client.get("/v1/access/me", headers=verified)).json()["email_invitation"] is True
    joined = await client.post("/v1/access/join", headers=verified, json={})
    assert joined.status_code == 200 and joined.json()["has_access"]
    # One person per email invitation.
    twin = bearer(oidc_auth, "ana-3", email="ana@studio.example", email_verified=True)
    assert (await client.post("/v1/access/join", headers=twin, json={})).status_code == 404


async def test_revoked_expired_and_suspended_access(v2, oidc_auth):  # noqa: F811
    client, factory, *_ = v2
    invite_mode()
    admin = admin_headers(oidc_auth)
    revoked = await make_key(client, admin, max_redemptions=5)
    response = await client.post(
        f"/v1/admin/access/invitations/{revoked['invitation']['id']}/revoke", headers=admin
    )
    assert response.status_code == 200 and response.json()["revoked_at"]
    guest = bearer(oidc_auth, "guest")
    late = await client.post("/v1/access/join", headers=guest, json={"key": revoked["key"]})
    assert late.status_code == 404

    expired = await make_key(client, admin)
    async with factory() as session:
        await session.execute(
            update(AccessInvitation)
            .where(AccessInvitation.id == UUID(expired["invitation"]["id"]))
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()
    assert (
        await client.post("/v1/access/join", headers=guest, json={"key": expired["key"]})
    ).status_code == 404
    past = await client.post(
        "/v1/admin/access/invitations",
        headers=admin,
        json={"kind": "key", "label": "old", "expires_at": "2020-01-01T00:00:00Z"},
    )
    assert past.status_code == 422

    good = await make_key(client, admin)
    assert (
        await client.post("/v1/access/join", headers=guest, json={"key": good["key"]})
    ).status_code == 200
    grants = (await client.get("/v1/admin/access/grants", headers=admin)).json()["grants"]
    grant = next(item for item in grants if item["email"] == "guest@example.com")
    assert grant["invitation_label"] == "ACME demo" and grant["status"] == "active"
    suspended = await client.post(f"/v1/admin/access/grants/{grant['id']}/suspend", headers=admin)
    assert suspended.status_code == 200 and suspended.json()["status"] == "suspended"
    blocked = await client.get("/v1/workspaces", headers=guest)
    assert blocked.status_code == 403 and problem(blocked) == "access-required"
    assert (await client.get("/v1/access/me", headers=guest)).json()["status"] == "suspended"
    # A suspended person cannot rejoin with another key.
    another = await make_key(client, admin)
    assert (
        await client.post("/v1/access/join", headers=guest, json={"key": another["key"]})
    ).status_code == 403
    await client.post(f"/v1/admin/access/grants/{grant['id']}/resume", headers=admin)
    assert (await client.get("/v1/workspaces", headers=guest)).status_code == 200


async def test_generation_is_charged_against_each_users_limits(v2, oidc_auth):  # noqa: F811
    client, factory, _, owner, project = v2
    base, _ = await project("Limits", schema="2")
    tenant = owner["X-Tenant-ID"]
    guest_auth = bearer(oidc_auth, "guest")
    await client.get("/v1/workspaces", headers=guest_auth)  # the guest exists
    added = await client.post(
        f"/v1/workspaces/{tenant}/members",
        headers=owner,
        json={"oidc_issuer": OIDC_ISSUER, "oidc_subject": "guest", "role": "member"},
    )
    assert added.status_code in (200, 201), added.text
    configure(narrative_image_max_active_jobs_per_workspace=10)

    async def background(headers, count, key=None):
        return await client.post(
            f"{base}/assets/background-jobs",
            headers={**headers, "X-Tenant-ID": tenant},
            json={
                "description": "harbor at dusk",
                "count": count,
                "idempotency_key": key or str(uuid4()),
            },
        )

    # Open mode charges nobody.
    assert (await background(guest_auth, 1)).status_code == 202
    invite_mode(narrative_image_max_active_jobs_per_workspace=10)
    admin = admin_headers(oidc_auth)
    created = await make_key(client, admin, limits={"image": {"daily": 3, "total": 5}})
    assert (
        await client.post("/v1/access/join", headers=guest_auth, json={"key": created["key"]})
    ).status_code == 200

    replay = str(uuid4())
    assert (await background(guest_auth, 2, replay)).status_code == 202
    assert (await background(guest_auth, 2, replay)).status_code == 202  # the same job, free
    over = await background(guest_auth, 2)
    assert over.status_code == 429 and problem(over) == "usage-limit"
    assert "only 1 of your 3 per 24 hours" in over.json()["detail"]
    assert (await background(guest_auth, 1)).status_code == 202
    me = (await client.get("/v1/access/me", headers=guest_auth)).json()
    assert me["usage"]["image"] == {"day": 3, "total": 3}
    async with factory() as session:
        rows = await session.scalar(select(func.count(UsageCharge.id)))
    assert rows == 2
