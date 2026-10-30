"""Studio scene hierarchy: viewers read, members reorganize; story content is untouched."""

from uuid import UUID

from fastapi import APIRouter

from flint_graph.api.dependencies import CurrentUserDep, SessionDep, TenantIdDep, TenantMemberDep
from flint_graph.api.narrative_layout_schemas import LayoutResponse, LayoutWrite
from flint_graph.api.routes.narrative import _persist
from flint_graph.application.services.narrative_layouts import get_layout, save_layout

router = APIRouter(prefix="/v1/narrative/projects/{project_id}/layout", tags=["narrative"])


@router.get("", response_model=LayoutResponse)
async def get_layout_endpoint(
    project_id: UUID, tenant_id: TenantIdDep, session: SessionDep, include_archived: bool = False
) -> LayoutResponse:
    version, items = await get_layout(
        session, tenant_id=tenant_id, project_id=project_id, include_archived=include_archived
    )
    return LayoutResponse.model_validate(
        {"project_id": project_id, "version": version, "items": items}
    )


@router.put("", response_model=LayoutResponse)
async def save_layout_endpoint(
    project_id: UUID,
    payload: LayoutWrite,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> LayoutResponse:
    items = [item.model_dump() for item in payload.items]
    row = await _persist(
        session,
        save_layout(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            base_version=payload.base_version,
            items=items,
            user_id=current_user.user.id,
        ),
    )
    return LayoutResponse.model_validate(
        {"project_id": project_id, "version": row.version, "items": row.items}
    )
