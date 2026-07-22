from fastapi import APIRouter, status

from flint_graph.api.dependencies import CurrentUserDep, SessionDep
from flint_graph.api.schemas import TenantCreate, TenantResponse
from flint_graph.application.services.authz import add_workspace_member
from flint_graph.application.services.tenants import create_tenant
from flint_graph.domain.enums import WorkspaceRole

router = APIRouter(prefix="/v1/tenants", tags=["tenants"])


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant_endpoint(
    payload: TenantCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> TenantResponse:
    tenant = await create_tenant(session, name=payload.name)
    await add_workspace_member(
        session,
        tenant_id=tenant.id,
        user_id=current_user.user.id,
        role=WorkspaceRole.OWNER,
    )
    return TenantResponse.model_validate(tenant)
