"""The audit ledger records who did what, including denied attempts.

These tests drive the real API so a privileged route that forgets to record an
audit event fails here rather than being discovered after an incident.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from flint_graph.application.services.audit import AuditActor, record_audit_event
from flint_graph.domain.enums import AuditAction, AuditOutcome
from flint_graph.infrastructure.db.models import AuditEvent, Tenant

# The oidc_auth fixture comes from conftest.py: audit events must carry a real
# authenticated identity, which dev auth's fixed principal cannot demonstrate.
OIDC_ISSUER = "https://keycloak.example/realms/flintgraph"


async def _audit_events(client, token: str, workspace_id: str, **params: object) -> list[dict]:
    response = await client.get(
        "/v1/audit-events",
        headers={"Authorization": f"Bearer {token}", "X-Tenant-ID": workspace_id},
        params=params,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _workspace(client, token: str, name: str = "Audited") -> dict:
    created = await client.post(
        "/v1/workspaces",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name},
    )
    assert created.status_code == 201, created.text
    return created.json()


async def test_workspace_creation_is_audited_with_actor_identity(client, oidc_auth) -> None:
    token = oidc_auth("owner-1")

    workspace = await _workspace(client, token, "Finance")
    events = await _audit_events(client, token, workspace["id"])

    assert [event["action"] for event in events] == [AuditAction.WORKSPACE_CREATED.value]
    event = events[0]
    assert event["outcome"] == AuditOutcome.ALLOWED.value
    assert event["actor_subject"] == "owner-1"
    assert event["actor_issuer"] == OIDC_ISSUER
    assert event["actor_user_id"] is not None
    assert event["resource_type"] == "workspace"
    assert event["resource_id"] == workspace["id"]
    assert event["request_id"]
    assert event["metadata"]["name"] == "Finance"


async def test_document_lifecycle_actions_each_record_exactly_one_event(
    client, oidc_auth
) -> None:
    token = oidc_auth("owner-1")
    workspace = await _workspace(client, token)
    headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": workspace["id"]}

    document = await client.post(
        "/v1/documents",
        headers=headers,
        json={"title": "Acme brief", "source_type": "upload"},
    )
    assert document.status_code == 201, document.text
    document_id = document.json()["id"]

    job = await client.post(
        f"/v1/documents/{document_id}/ingestion-jobs",
        headers={**headers, "Idempotency-Key": "audit-job-key-1"},
    )
    assert job.status_code == 201, job.text

    # A replayed idempotency key creates nothing, so it must not add an event.
    replay = await client.post(
        f"/v1/documents/{document_id}/ingestion-jobs",
        headers={**headers, "Idempotency-Key": "audit-job-key-1"},
    )
    assert replay.status_code == 200

    deleted = await client.delete(f"/v1/documents/{document_id}", headers=headers)
    assert deleted.status_code == 200, deleted.text

    events = await _audit_events(client, token, workspace["id"])
    actions = [event["action"] for event in events]

    assert actions.count(AuditAction.DOCUMENT_CREATED.value) == 1
    assert actions.count(AuditAction.INGESTION_JOB_CREATED.value) == 1
    assert actions.count(AuditAction.DOCUMENT_DELETED.value) == 1
    deletion = next(
        event for event in events if event["action"] == AuditAction.DOCUMENT_DELETED.value
    )
    assert deletion["resource_id"] == document_id


async def test_denied_privileged_attempt_is_recorded_as_denied(client, oidc_auth) -> None:
    owner_token = oidc_auth("owner-1")
    viewer_token = oidc_auth("viewer-1")
    workspace = await _workspace(client, owner_token, "Legal")

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

    denied = await client.post(
        f"/v1/workspaces/{workspace['id']}/members",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={
            "oidc_subject": "intruder",
            "email": "intruder@example.com",
            "display_name": "Intruder",
            "role": "admin",
        },
    )
    assert denied.status_code == 403

    events = await _audit_events(
        client,
        owner_token,
        workspace["id"],
        outcome=AuditOutcome.DENIED.value,
    )

    assert len(events) == 1
    assert events[0]["action"] == AuditAction.WORKSPACE_MEMBER_UPSERTED.value
    assert events[0]["actor_subject"] == "viewer-1"
    assert events[0]["metadata"]["requested_role"] == "admin"
    assert events[0]["metadata"]["actor_role"] == "viewer"


async def test_audit_reads_require_admin_and_never_cross_workspaces(
    client, oidc_auth
) -> None:
    owner_token = oidc_auth("owner-1")
    viewer_token = oidc_auth("viewer-1")
    first = await _workspace(client, owner_token, "First")
    second = await _workspace(client, oidc_auth("other-owner"), "Second")

    await client.post(
        f"/v1/workspaces/{first['id']}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "oidc_subject": "viewer-1",
            "email": "viewer-1@example.com",
            "display_name": "Viewer One",
            "role": "viewer",
        },
    )

    viewer_response = await client.get(
        "/v1/audit-events",
        headers={"Authorization": f"Bearer {viewer_token}", "X-Tenant-ID": first["id"]},
    )
    assert viewer_response.status_code == 403

    cross_workspace = await client.get(
        "/v1/audit-events",
        headers={"Authorization": f"Bearer {owner_token}", "X-Tenant-ID": second["id"]},
    )
    assert cross_workspace.status_code == 403

    own_events = await _audit_events(client, owner_token, first["id"])
    assert {event["tenant_id"] for event in own_events} == {first["id"]}


async def test_audit_events_can_be_filtered_by_action(client, oidc_auth) -> None:
    token = oidc_auth("owner-1")
    workspace = await _workspace(client, token)
    headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": workspace["id"]}
    await client.post(
        "/v1/documents",
        headers=headers,
        json={"title": "Filterable", "source_type": "upload"},
    )

    events = await _audit_events(
        client,
        token,
        workspace["id"],
        action=AuditAction.DOCUMENT_CREATED.value,
    )

    assert [event["action"] for event in events] == [AuditAction.DOCUMENT_CREATED.value]


@pytest.mark.anyio
async def test_rolled_back_transaction_leaves_no_audit_row(db_session) -> None:
    """The ledger shares the mutation's transaction, so a rollback takes it too."""
    tenant = Tenant(name="Rollback")
    db_session.add(tenant)
    await db_session.flush()

    await record_audit_event(
        db_session,
        action=AuditAction.DOCUMENT_DELETED,
        actor=AuditActor(user_id=None, subject="who", request_id="req-1"),
        tenant_id=tenant.id,
        resource_type="document",
        resource_id=uuid4(),
    )
    assert await db_session.scalar(select(func.count(AuditEvent.id))) == 1

    await db_session.rollback()

    assert await db_session.scalar(select(func.count(AuditEvent.id))) == 0
