from fastapi import APIRouter, status

from flint_graph.api.dependencies import SessionDep
from flint_graph.api.schemas import TenantCreate, TenantResponse
from flint_graph.application.services.tenants import create_tenant

router = APIRouter(prefix="/v1/tenants", tags=["tenants"])


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant_endpoint(payload: TenantCreate, session: SessionDep) -> TenantResponse:
    tenant = await create_tenant(session, name=payload.name)
    return TenantResponse.model_validate(tenant)