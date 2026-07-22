from uuid import uuid4

import pytest

from flint_graph.application.services.authz import (
    AuthenticatedPrincipal,
    WorkspaceRole,
    add_workspace_member,
    get_workspace_role,
    require_workspace_role,
    upsert_user_from_principal,
)
from flint_graph.config import Settings
from flint_graph.domain.errors import ForbiddenError
from flint_graph.infrastructure.db.models import Tenant


def test_production_rejects_dev_auth_mode_by_default() -> None:
    with pytest.raises(ValueError, match="auth_mode='dev' is not allowed"):
        Settings(env="production", auth_mode="dev")


async def test_upsert_user_and_workspace_membership_authorize_roles(db_session) -> None:
    tenant = Tenant(name="Finance")
    db_session.add(tenant)
    await db_session.flush()

    principal = AuthenticatedPrincipal(
        issuer="https://keycloak.example/realms/flintgraph",
        subject="user-123",
        email="analyst@example.com",
        display_name="Analyst",
        claims={"preferred_username": "analyst"},
    )

    user = await upsert_user_from_principal(db_session, principal)
    same_user = await upsert_user_from_principal(db_session, principal)
    assert same_user.id == user.id

    membership = await add_workspace_member(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        role=WorkspaceRole.MEMBER,
    )
    assert membership.role == WorkspaceRole.MEMBER

    role = await get_workspace_role(db_session, tenant_id=tenant.id, user_id=user.id)
    assert role == WorkspaceRole.MEMBER
    require_workspace_role(role, allowed={WorkspaceRole.VIEWER, WorkspaceRole.MEMBER})

    with pytest.raises(ForbiddenError):
        require_workspace_role(role, allowed={WorkspaceRole.ADMIN, WorkspaceRole.OWNER})


async def test_missing_membership_has_no_workspace_role(db_session) -> None:
    tenant = Tenant(name="Legal")
    db_session.add(tenant)
    await db_session.flush()

    role = await get_workspace_role(db_session, tenant_id=tenant.id, user_id=uuid4())
    assert role is None
