"""Workspace names belong to the people using them, not to the whole server."""

import asyncio
from uuid import UUID

import pytest
from sqlalchemy import select

from flint_graph.domain.enums import WorkspaceMembershipStatus
from flint_graph.infrastructure.db.models import WorkspaceMembership

pytestmark = pytest.mark.anyio


def signed_in(oidc_auth, subject: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + oidc_auth(subject)}


async def create(client, headers, name, path="/v1/workspaces"):
    return await client.post(path, headers=headers, json={"name": name})


async def names(client, headers):
    response = await client.get("/v1/workspaces", headers=headers)
    assert response.status_code == 200, response.text
    return [row["name"] for row in response.json()]


async def test_two_people_can_use_the_same_name(narrative_env, oidc_auth):
    client, _, _ = narrative_env
    alice, bob = signed_in(oidc_auth, "alice"), signed_in(oidc_auth, "bob")
    first = await create(client, alice, "My studio")
    second = await create(client, bob, "My studio")
    assert first.status_code == second.status_code == 201, second.text
    assert first.json()["id"] != second.json()["id"]
    # Same name, separate workspaces: neither can see the other's.
    assert await names(client, alice) == ["My studio"]
    assert await names(client, bob) == ["My studio"]
    theirs = await client.post(
        "/v1/narrative/projects",
        headers={**bob, "X-Tenant-ID": first.json()["id"]},
        json={"name": "Trespass", "idempotency_key": "00000000-0000-4000-8000-000000000001"},
    )
    assert theirs.status_code == 403


async def test_one_person_cannot_have_two_with_the_same_name(narrative_env, oidc_auth):
    client, _, _ = narrative_env
    alice = signed_in(oidc_auth, "alice")
    assert (await create(client, alice, "My studio")).status_code == 201
    for repeat in ("My studio", "my STUDIO", "  My studio  "):
        again = await create(client, alice, repeat)
        assert again.status_code == 409, repeat
        assert "already have a workspace" in again.json()["detail"]
    assert await names(client, alice) == ["My studio"]


async def test_a_refusal_never_reveals_anyone_elses_workspace(narrative_env, oidc_auth):
    client, _, _ = narrative_env
    alice, bob = signed_in(oidc_auth, "alice"), signed_in(oidc_auth, "bob")
    await create(client, alice, "Secret project")
    # Before, this was refused, which told Bob the name was taken.
    assert (await create(client, bob, "Secret project")).status_code == 201


async def test_the_older_tenants_route_follows_the_same_rule(narrative_env, oidc_auth):
    client, _, _ = narrative_env
    alice, bob = signed_in(oidc_auth, "alice"), signed_in(oidc_auth, "bob")
    assert (await create(client, alice, "Shared", path="/v1/tenants")).status_code == 201
    assert (await create(client, bob, "Shared", path="/v1/tenants")).status_code == 201
    assert (await create(client, alice, "Shared", path="/v1/tenants")).status_code == 409
    assert (await create(client, alice, "Shared")).status_code == 409


async def test_a_workspace_you_left_does_not_hold_its_name(narrative_env, oidc_auth):
    client, factory, _ = narrative_env
    alice = signed_in(oidc_auth, "alice")
    old = await create(client, alice, "My studio")
    async with factory() as session:
        membership = await session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.tenant_id == UUID(old.json()["id"])
            )
        )
        membership.status = WorkspaceMembershipStatus.DISABLED
        await session.commit()
    assert await names(client, alice) == []
    assert (await create(client, alice, "My studio")).status_code == 201


async def test_a_name_must_still_say_something(narrative_env, oidc_auth):
    client, _, _ = narrative_env
    alice = signed_in(oidc_auth, "alice")
    assert (await create(client, alice, "    ")).status_code == 422
    made = await create(client, alice, "  Trimmed  ")
    assert made.json()["name"] == "Trimmed"


async def test_a_double_click_makes_one_workspace(narrative_env, oidc_auth):
    client, factory, _ = narrative_env
    if factory.kw["bind"].dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-lock qualification")
    alice = signed_in(oidc_auth, "alice")
    # Signing in once first, so the requests race on the name and not on creating the user.
    await names(client, alice)
    responses = await asyncio.gather(*(create(client, alice, "My studio") for _ in range(4)))
    assert sorted(response.status_code for response in responses) == [201, 409, 409, 409]
    assert await names(client, alice) == ["My studio"]
