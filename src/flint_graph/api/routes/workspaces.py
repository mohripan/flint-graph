from uuid import UUID

from fastapi import APIRouter, status

from flint_graph.api.dependencies import CurrentUserDep, SessionDep, SettingsDep
from flint_graph.api.schemas import (
    WorkspaceCreate,
    WorkspaceMemberCreate,
    WorkspaceMemberResponse,
    WorkspaceResponse,
)
from flint_graph.application.services.authz import (
    get_workspace_role,
    require_workspace_role,
    role_at_least,
)
from flint_graph.application.services.workspaces import (
    add_workspace_member_by_identity,
    create_workspace_for_user,
    list_workspaces_for_user,
)
from flint_graph.domain.enums import WorkspaceRole
from flint_graph.domain.errors import BadRequestError

router = APIRouter(prefix="/v1/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces_endpoint(
    current_user: CurrentUserDep,
    session: SessionDep,
) -> list[WorkspaceResponse]:
    workspaces = await list_workspaces_for_user(session, user_id=current_user.user.id)
    return [WorkspaceResponse(id=item.id, name=item.name, role=item.role) for item in workspaces]


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace_endpoint(
    payload: WorkspaceCreate,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> WorkspaceResponse:
    workspace = await create_workspace_for_user(
        session,
        name=payload.name,
        user_id=current_user.user.id,
    )
    return WorkspaceResponse(id=workspace.id, name=workspace.name, role=workspace.role)


@router.post(
    "/{workspace_id}/members",
    response_model=WorkspaceMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_workspace_member_endpoint(
    workspace_id: UUID,
    payload: WorkspaceMemberCreate,
    current_user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
) -> WorkspaceMemberResponse:
    actor_role = await get_workspace_role(
        session,
        tenant_id=workspace_id,
        user_id=current_user.user.id,
    )
    require_workspace_role(actor_role, allowed=role_at_least(WorkspaceRole.ADMIN))
    issuer = payload.oidc_issuer or settings.oidc_issuer
    if issuer is None:
        raise BadRequestError("oidc_issuer is required when no default OIDC issuer is configured.")
    member = await add_workspace_member_by_identity(
        session,
        tenant_id=workspace_id,
        oidc_issuer=issuer,
        oidc_subject=payload.oidc_subject,
        email=payload.email,
        display_name=payload.display_name,
        role=payload.role,
    )
    return WorkspaceMemberResponse(
        user_id=member.user_id,
        email=member.email,
        display_name=member.display_name,
        role=member.role,
    )
