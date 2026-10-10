from uuid import uuid4

from flint_graph.api.dependencies import get_index_backfill_workflow_starter

# The oidc_auth / oidc_settings_override fixtures live in conftest.py so other
# suites (audit, usage) can authenticate as distinct real users too.


class CapturingBackfillStarter:
    def __init__(self) -> None:
        self.started: list[str] = []

    async def start_index_backfill_workflow(self, *, job_id: object) -> None:
        self.started.append(str(job_id))


async def test_oidc_mode_rejects_unauthenticated_tenant_scoped_requests(
    client,
    oidc_settings_override,
) -> None:
    response = await client.get(
        "/v1/search-readiness",
        headers={"X-Tenant-ID": str(uuid4())},
    )

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_oidc_mode_rejects_unauthenticated_workspace_creation(
    client,
    oidc_settings_override,
) -> None:
    response = await client.post("/v1/tenants", json={"name": "Untrusted"})

    assert response.status_code == 401


async def test_oidc_user_creates_workspace_as_owner_and_lists_it(
    client,
    oidc_auth,
) -> None:
    token = oidc_auth("owner-1")

    created = await client.post(
        "/v1/workspaces",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Finance"},
    )
    assert created.status_code == 201
    created_body = created.json()
    assert created_body["name"] == "Finance"
    assert created_body["role"] == "owner"

    listed = await client.get(
        "/v1/workspaces",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listed.status_code == 200
    assert listed.json() == [created_body]


async def test_workspace_owner_adds_viewer_and_viewer_cannot_manage_members(
    client,
    oidc_auth,
) -> None:
    owner_token = oidc_auth("owner-1")
    viewer_token = oidc_auth("viewer-1")

    workspace = (
        await client.post(
            "/v1/workspaces",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "Legal"},
        )
    ).json()

    added = await client.post(
        f"/v1/workspaces/{workspace['id']}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "oidc_subject": "viewer-1",
            "email": "viewer-1@example.com",
            "display_name": "Viewer One",
            "role": "viewer",
        },
    )
    assert added.status_code == 201
    assert added.json()["role"] == "viewer"

    listed = await client.get(
        "/v1/workspaces",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert listed.status_code == 200
    assert listed.json() == [{"id": workspace["id"], "name": "Legal", "role": "viewer"}]

    denied = await client.post(
        f"/v1/workspaces/{workspace['id']}/members",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={
            "oidc_subject": "other-user",
            "email": "other@example.com",
            "display_name": "Other User",
            "role": "viewer",
        },
    )
    assert denied.status_code == 403


async def test_workspace_viewer_cannot_delete_documents(client, oidc_auth) -> None:
    owner_token = oidc_auth("owner-1")
    viewer_token = oidc_auth("viewer-1")

    workspace = (
        await client.post(
            "/v1/workspaces",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "Research"},
        )
    ).json()
    await client.post(
        f"/v1/workspaces/{workspace['id']}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "oidc_subject": "viewer-1",
            "email": "viewer-1@example.com",
            "display_name": "Viewer One",
            "role": "viewer",
        },
    )
    document = (
        await client.post(
            "/v1/documents",
            headers={
                "Authorization": f"Bearer {owner_token}",
                "X-Tenant-ID": workspace["id"],
            },
            json={"title": "Roadmap", "source_type": "upload"},
        )
    ).json()

    denied = await client.delete(
        f"/v1/documents/{document['id']}",
        headers={
            "Authorization": f"Bearer {viewer_token}",
            "X-Tenant-ID": workspace["id"],
        },
    )

    assert denied.status_code == 403


async def test_workspace_viewer_cannot_mutate_graph_review_state(client, oidc_auth) -> None:
    owner_token = oidc_auth("owner-1")
    viewer_token = oidc_auth("viewer-1")

    workspace = (
        await client.post(
            "/v1/workspaces",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "Graph Review"},
        )
    ).json()
    await client.post(
        f"/v1/workspaces/{workspace['id']}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "oidc_subject": "viewer-1",
            "email": "viewer-1@example.com",
            "display_name": "Viewer One",
            "role": "viewer",
        },
    )

    denied = await client.post(
        f"/v1/merge-reviews/{uuid4()}/decision",
        headers={
            "Authorization": f"Bearer {viewer_token}",
            "X-Tenant-ID": workspace["id"],
        },
        json={"decision": "accept", "actor": "viewer-1", "reason": "no permission"},
    )

    assert denied.status_code == 403


async def test_workspace_admin_can_bootstrap_retrieval_index_but_viewer_cannot(
    client,
    oidc_auth,
) -> None:
    owner_token = oidc_auth("owner-1")
    viewer_token = oidc_auth("viewer-1")
    workspace = (
        await client.post(
            "/v1/workspaces",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "Operations"},
        )
    ).json()
    await client.post(
        f"/v1/workspaces/{workspace['id']}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "oidc_subject": "viewer-1",
            "email": "viewer-1@example.com",
            "display_name": "Viewer One",
            "role": "viewer",
        },
    )

    created = await client.post(
        "/v1/retrieval-index/bootstrap",
        headers={
            "Authorization": f"Bearer {owner_token}",
            "X-Tenant-ID": workspace["id"],
        },
    )
    assert created.status_code == 200
    assert created.json()["status"] == "active"
    assert created.json()["scope"] == "tenant"
    assert created.json()["tenant_id"] == workspace["id"]

    denied = await client.post(
        "/v1/retrieval-index/bootstrap",
        headers={
            "Authorization": f"Bearer {viewer_token}",
            "X-Tenant-ID": workspace["id"],
        },
    )
    assert denied.status_code == 403


async def test_bootstrap_never_activates_another_owners_workspace_index(client, oidc_auth):
    indexes = []
    for subject in ("owner-first", "owner-second"):
        token = oidc_auth(subject)
        workspace = (await client.post(
            "/v1/workspaces", headers={"Authorization": f"Bearer {token}"},
            json={"name": subject},
        )).json()
        headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": workspace["id"]}
        first = await client.post("/v1/retrieval-index/bootstrap", headers=headers)
        assert first.status_code == 200
        assert first.json()["tenant_id"] == workspace["id"]
        repeated = await client.post("/v1/retrieval-index/bootstrap", headers=headers)
        assert repeated.json()["id"] == first.json()["id"]
        indexes.append(first.json()["id"])
    assert indexes[0] != indexes[1]


async def test_workspace_document_list_is_server_backed_and_tenant_scoped(
    client,
    oidc_auth,
) -> None:
    owner_token = oidc_auth("owner-1")
    other_token = oidc_auth("other-1")
    workspace = (
        await client.post(
            "/v1/workspaces",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "Knowledge"},
        )
    ).json()
    other_workspace = (
        await client.post(
            "/v1/workspaces",
            headers={"Authorization": f"Bearer {other_token}"},
            json={"name": "Other Knowledge"},
        )
    ).json()
    document = (
        await client.post(
            "/v1/documents",
            headers={
                "Authorization": f"Bearer {owner_token}",
                "X-Tenant-ID": workspace["id"],
            },
            json={"title": "Roadmap", "source_type": "upload"},
        )
    ).json()

    listed = await client.get(
        "/v1/documents",
        headers={
            "Authorization": f"Bearer {owner_token}",
            "X-Tenant-ID": workspace["id"],
        },
    )
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == document["id"]
    assert listed.json()[0]["title"] == "Roadmap"

    foreign = await client.get(
        "/v1/documents",
        headers={
            "Authorization": f"Bearer {other_token}",
            "X-Tenant-ID": other_workspace["id"],
        },
    )
    assert foreign.status_code == 200
    assert foreign.json() == []


async def test_query_history_endpoint_is_tenant_scoped(client, oidc_auth) -> None:
    owner_token = oidc_auth("owner-1")
    workspace = (
        await client.post(
            "/v1/workspaces",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "Questions"},
        )
    ).json()

    response = await client.get(
        "/v1/query-runs",
        headers={
            "Authorization": f"Bearer {owner_token}",
            "X-Tenant-ID": workspace["id"],
        },
    )

    assert response.status_code == 200
    assert response.json() == []


async def test_system_readiness_reports_auth_mode_and_search_readiness(
    client,
    oidc_auth,
) -> None:
    owner_token = oidc_auth("owner-1")
    workspace = (
        await client.post(
            "/v1/workspaces",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "Setup"},
        )
    ).json()

    response = await client.get(
        "/v1/system-readiness",
        headers={
            "Authorization": f"Bearer {owner_token}",
            "X-Tenant-ID": workspace["id"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["auth"]["mode"] == "oidc"
    assert body["embedding"]["provider"]
    assert body["embedding"]["model"]
    assert body["query"]["answer_provider"]
    assert body["search_readiness"]["reason"] == "no_active_index"


async def test_workspace_admin_can_backfill_active_index(client, oidc_auth) -> None:
    from flint_graph.main import app

    starter = CapturingBackfillStarter()
    app.dependency_overrides[get_index_backfill_workflow_starter] = lambda: starter
    try:
        owner_token = oidc_auth("owner-1")
        workspace = (
            await client.post(
                "/v1/workspaces",
                headers={"Authorization": f"Bearer {owner_token}"},
                json={"name": "Backfill"},
            )
        ).json()
        await client.post(
            "/v1/retrieval-index/bootstrap",
            headers={
                "Authorization": f"Bearer {owner_token}",
                "X-Tenant-ID": workspace["id"],
            },
        )

        response = await client.post(
            "/v1/retrieval-index/backfill-active",
            headers={
                "Authorization": f"Bearer {owner_token}",
                "X-Tenant-ID": workspace["id"],
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "queued"
        assert body["tenant_id"] == workspace["id"]
        assert starter.started == [body["id"]]

        listed = await client.get(
            "/v1/index-backfills",
            headers={
                "Authorization": f"Bearer {owner_token}",
                "X-Tenant-ID": workspace["id"],
            },
        )
        assert listed.status_code == 200
        assert [job["id"] for job in listed.json()] == [body["id"]]
    finally:
        app.dependency_overrides.pop(get_index_backfill_workflow_starter, None)
