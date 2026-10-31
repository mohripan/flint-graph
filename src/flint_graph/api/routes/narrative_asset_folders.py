"""Asset folders: editor-only organization of the project library (ADR 0043).

Viewers read the folder tree and its counts; members change it.
"""

from uuid import UUID

from fastapi import APIRouter, Response

from flint_graph.api.dependencies import CurrentUserDep, SessionDep, TenantIdDep, TenantMemberDep
from flint_graph.api.narrative_character_schemas import (
    FolderCreate,
    FolderResponse,
    FolderUpdate,
    LibraryIndexResponse,
)
from flint_graph.api.routes.narrative import _persist
from flint_graph.application.services.narrative_asset_folders import (
    create_folder,
    delete_folder,
    library_index,
    update_folder,
)
from flint_graph.infrastructure.db.models import NarrativeAssetFolder

router = APIRouter(prefix="/v1/narrative/projects/{project_id}/asset-folders", tags=["narrative"])


def _folder(row: NarrativeAssetFolder, count: int = 0) -> FolderResponse:
    return FolderResponse(id=row.id, parent_id=row.parent_id, name=row.name, asset_count=count)


@router.get("", response_model=LibraryIndexResponse)
async def library_index_endpoint(
    project_id: UUID, tenant_id: TenantIdDep, session: SessionDep
) -> LibraryIndexResponse:
    found = await library_index(session, tenant_id=tenant_id, project_id=project_id)
    return LibraryIndexResponse(
        folders=[_folder(row, count) for row, count in found.folders],
        unfiled=found.unfiled,
        to_review=found.to_review,
        total=found.total,
        kinds=found.kinds,
        characters=found.characters,
    )


@router.post("", response_model=FolderResponse, status_code=201)
async def create_folder_endpoint(
    project_id: UUID,
    payload: FolderCreate,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> FolderResponse:
    row = await _persist(
        session,
        create_folder(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            name=payload.name,
            parent_id=payload.parent_id,
            author_user_id=current_user.user.id,
        ),
    )
    return _folder(row)


@router.patch("/{folder_id}", response_model=FolderResponse)
async def update_folder_endpoint(
    project_id: UUID,
    folder_id: UUID,
    payload: FolderUpdate,
    tenant_id: TenantMemberDep,
    session: SessionDep,
) -> FolderResponse:
    changes = {"parent_id": payload.parent_id} if "parent_id" in payload.model_fields_set else {}
    row = await _persist(
        session,
        update_folder(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            folder_id=folder_id,
            name=payload.name,
            **changes,
        ),
    )
    return _folder(row)


@router.delete("/{folder_id}", status_code=204)
async def delete_folder_endpoint(
    project_id: UUID, folder_id: UUID, tenant_id: TenantMemberDep, session: SessionDep
) -> Response:
    """Its subfolders and assets move to its parent folder."""
    await _persist(
        session,
        delete_folder(session, tenant_id=tenant_id, project_id=project_id, folder_id=folder_id),
    )
    return Response(status_code=204)
