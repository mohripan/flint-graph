"""The balance of someone nothing is enforced on: it counts down and never stops them (ADR 0074)."""

import pytest
from sqlalchemy import func, select
from test_access_credits_api import background, me
from test_access_invitations_api import ADMIN, admin_headers, invite_mode, make_key
from test_narrative_package_v2_api import configure, v2  # noqa: F401

from flint_graph.application.services.access import act_for, charge_usage
from flint_graph.config import Settings
from flint_graph.infrastructure.db.models import AccessGrant, User

pytestmark = pytest.mark.anyio


async def history(client, headers):
    entries = (await client.get("/v1/access/credits", headers=headers)).json()["entries"]
    return [(item["change"], item["amount"], item["balance"]) for item in reversed(entries)]


async def test_on_your_own_server_the_balance_counts_down_with_a_history(v2):  # noqa: F811
    client, _, _, owner, project = v2
    base, _ = await project("Own", schema="2")
    configure(access_default_credits=100, narrative_image_max_active_jobs_per_workspace=50)

    status = await me(client, owner)
    assert status["keeps_going"] is True
    assert status["credits"] == 100, "the balance shows before anything is spent"
    assert await history(client, owner) == []

    assert (await background(client, base, owner, 4)).status_code == 202  # 4 × 2
    status = await me(client, owner)
    assert status["credits"] == 92
    assert status["usage"]["image"]["total"] == 4
    assert await history(client, owner) == [("join", 100, 100), ("charge", -8, 92)]

    assert (await background(client, base, owner, 1)).status_code == 202
    assert (await me(client, owner))["credits"] == 90


async def test_at_zero_it_shows_zero_and_carries_on(v2):  # noqa: F811
    client, _, _, owner, project = v2
    base, _ = await project("Own", schema="2")
    configure(access_default_credits=6, narrative_image_max_active_jobs_per_workspace=50)

    assert (await background(client, base, owner, 4)).status_code == 202
    assert (await me(client, owner))["credits"] == 0
    assert (await background(client, base, owner, 4)).status_code == 202, "never blocked"
    status = await me(client, owner)
    assert status["credits"] == 0, "and never below zero"
    assert status["usage"]["image"]["total"] == 8, "what was really made still counts"
    assert await history(client, owner) == [("join", 6, 6), ("charge", -8, 0), ("charge", -8, 0)]


async def test_an_operator_counts_down_without_ever_getting_a_grant(v2, oidc_auth):  # noqa: F811
    client, factory, *_ = v2
    invite_mode(access_default_credits=50, narrative_image_max_active_jobs_per_workspace=50)
    admin = admin_headers(oidc_auth)
    status = await me(client, admin)
    assert (status["is_admin"], status["keeps_going"], status["credits"]) == (True, True, 50)

    workspace = (await client.post("/v1/workspaces", headers=admin, json={"name": "Mine"})).json()
    headers = {**admin, "X-Tenant-ID": workspace["id"]}
    created = await client.post(
        "/v1/narrative/projects",
        headers=headers,
        json={"name": "Mine", "idempotency_key": "6f4a7b1e-1b1c-4a53-9d0e-111111111111"},
    )
    base = f"/v1/narrative/projects/{created.json()['id']}"
    assert (await background(client, base, headers, 4)).status_code == 202
    assert (await me(client, admin))["credits"] == 42
    async with factory() as session:
        assert await session.scalar(select(func.count(AccessGrant.id))) == 0


async def test_no_access_comes_from_the_balance_alone(v2, oidc_auth):  # noqa: F811
    client, _, _, _, _ = v2
    invite_mode(access_default_credits=50, narrative_image_max_active_jobs_per_workspace=50)
    admin = admin_headers(oidc_auth)
    workspace = (await client.post("/v1/workspaces", headers=admin, json={"name": "Was"})).json()
    headers = {**admin, "X-Tenant-ID": workspace["id"]}
    created = await client.post(
        "/v1/narrative/projects",
        headers=headers,
        json={"name": "Was", "idempotency_key": "6f4a7b1e-1b1c-4a53-9d0e-222222222222"},
    )
    base = f"/v1/narrative/projects/{created.json()['id']}"
    assert (await background(client, base, headers, 1)).status_code == 202

    configure(access_admin_emails=[])
    status = await me(client, admin)
    assert (status["has_access"], status["keeps_going"]) == (False, False)
    assert status["credits"] is None
    assert (await client.get("/v1/workspaces", headers=admin)).status_code == 403


async def test_own_server_work_is_not_held_against_a_later_key(v2, oidc_auth):  # noqa: F811
    client, _, _, owner, project = v2
    base, _ = await project("Before", schema="2")
    configure(narrative_image_max_active_jobs_per_workspace=50)
    assert (await background(client, base, owner, 4)).status_code == 202
    assert (await me(client, owner))["usage"]["image"]["total"] == 4

    invite_mode(narrative_image_max_active_jobs_per_workspace=50)
    created = await make_key(
        client, admin_headers(oidc_auth), credits=100, limits={"image": {"daily": 3}}
    )
    await client.post("/v1/access/join", headers=owner, json={"key": created["key"]})
    status = await me(client, owner)
    assert status["usage"]["image"]["total"] == 0
    assert (await background(client, base, owner, 3)).status_code == 202, "the whole allowance"
    assert (await background(client, base, owner, 1)).status_code == 429


async def test_invited_people_still_stop_at_zero(v2, oidc_auth):  # noqa: F811
    client, _, _, owner, project = v2
    base, _ = await project("Invited", schema="2")
    invite_mode(narrative_image_max_active_jobs_per_workspace=50)
    admin = admin_headers(oidc_auth)
    created = await make_key(client, admin, credits=4)
    await client.post("/v1/access/join", headers=owner, json={"key": created["key"]})
    status = await me(client, owner)
    assert (status["keeps_going"], status["credits"], status["unlimited"]) == (False, 4, False)
    assert (await background(client, base, owner, 2)).status_code == 202
    refused = await background(client, base, owner, 1)
    assert refused.status_code == 402


async def test_an_unlimited_key_still_says_unlimited(v2, oidc_auth):  # noqa: F811
    client, _, _, owner, _ = v2
    invite_mode()
    created = await make_key(client, admin_headers(oidc_auth), unlimited=True)
    await client.post("/v1/access/join", headers=owner, json={"key": created["key"]})
    status = await me(client, owner)
    assert (status["keeps_going"], status["unlimited"]) == (False, True)


async def test_work_a_worker_starts_later_counts_for_an_operator_too(v2, oidc_auth):  # noqa: F811
    client, factory, *_ = v2
    invite_mode(access_default_credits=50)
    admin = admin_headers(oidc_auth)
    await me(client, admin)
    settings = Settings(env="test").model_copy(
        update={"access_mode": "invite", "access_default_credits": 50}
    )
    async with factory() as session:
        user_id = await session.scalar(select(User.id).where(User.email == ADMIN))
        act_for(session, user_id=user_id, settings=settings)
        await charge_usage(session, user_id=user_id, item="image.standard", units=3)
        await session.commit()
    assert (await me(client, admin))["credits"] == 44
