"""Asset folders: editor-only organization of a project's library (ADR 0043).

Folders and an asset's place in them never change asset bytes, hashes, story
packages, revisions or releases. Every change locks the project row, which also
serializes the sibling-name and depth checks.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.narrative_projects import get_project
from flint_graph.domain.errors import ConflictError, DomainError, NotFoundError
from flint_graph.infrastructure.db.models import NarrativeAsset, NarrativeAssetFolder

MAX_DEPTH = 3
NAME_LIMIT = 80
MOVE_LIMIT = 100


def _invalid(detail: str) -> DomainError:
    return DomainError(422, "Invalid folder", detail, "invalid-folder")


def clean_name(value: str) -> str:
    name = " ".join(value.split())
    if not name or len(name) > NAME_LIMIT:
        raise _invalid(f"Folder names have 1 to {NAME_LIMIT} characters.")
    return name


@dataclass(frozen=True)
class LibraryIndex:
    folders: list[tuple[NarrativeAssetFolder, int]]
    unfiled: int
    to_review: int
    total: int
    kinds: dict[str, int]
    characters: dict[str, int]


async def _folders(
    session: AsyncSession, tenant_id: UUID, project_id: UUID
) -> dict[UUID, NarrativeAssetFolder]:
    rows = await session.scalars(
        select(NarrativeAssetFolder)
        .where(
            NarrativeAssetFolder.tenant_id == tenant_id,
            NarrativeAssetFolder.project_id == project_id,
        )
        .order_by(func.lower(NarrativeAssetFolder.name), NarrativeAssetFolder.id)
    )
    return {row.id: row for row in rows}


async def library_index(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID
) -> LibraryIndex:
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    folders = await _folders(session, tenant_id, project_id)
    rows = (
        await session.execute(
            select(
                NarrativeAsset.folder_id,
                NarrativeAsset.kind,
                NarrativeAsset.character_id,
                NarrativeAsset.status,
            ).where(
                NarrativeAsset.tenant_id == tenant_id,
                NarrativeAsset.project_id == project_id,
                NarrativeAsset.status != "discarded",
            )
        )
    ).all()
    per_folder = Counter(row.folder_id for row in rows)
    return LibraryIndex(
        folders=[(folder, per_folder.get(folder.id, 0)) for folder in folders.values()],
        unfiled=per_folder.get(None, 0),
        to_review=sum(row.status == "candidate" for row in rows),
        total=len(rows),
        kinds=dict(sorted(Counter(row.kind for row in rows).items())),
        characters=dict(
            sorted(Counter(row.character_id for row in rows if row.character_id).items())
        ),
    )


async def _locked_project(session: AsyncSession, tenant_id: UUID, project_id: UUID) -> None:
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    if project.archived_at is not None:
        raise ConflictError("Restore this project before organizing assets.")


def _depth(folders: dict[UUID, NarrativeAssetFolder], folder_id: UUID | None) -> int:
    depth = 0
    while folder_id is not None:
        depth += 1
        folder_id = folders[folder_id].parent_id
    return depth


def _height(folders: dict[UUID, NarrativeAssetFolder], folder_id: UUID) -> int:
    """Levels in the subtree rooted at ``folder_id``, the folder itself included."""
    children = [item.id for item in folders.values() if item.parent_id == folder_id]
    return 1 + max((_height(folders, child) for child in children), default=0)


def _check_place(
    folders: dict[UUID, NarrativeAssetFolder],
    *,
    name: str,
    parent_id: UUID | None,
    moving: NarrativeAssetFolder | None = None,
) -> None:
    if parent_id is not None and parent_id not in folders:
        raise NotFoundError("Folder was not found.")
    if moving is not None:
        ancestor = parent_id
        while ancestor is not None:
            if ancestor == moving.id:
                raise _invalid("A folder cannot move into itself.")
            ancestor = folders[ancestor].parent_id
    height = _height(folders, moving.id) if moving is not None else 1
    if _depth(folders, parent_id) + height > MAX_DEPTH:
        raise _invalid(f"Folders nest at most {MAX_DEPTH} levels deep.")
    for other in folders.values():
        if (
            other.parent_id == parent_id
            and other.name.lower() == name.lower()
            and (moving is None or other.id != moving.id)
        ):
            raise ConflictError(f"A folder named “{other.name}” is already here.")


async def create_folder(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    name: str,
    parent_id: UUID | None,
    author_user_id: UUID,
) -> NarrativeAssetFolder:
    await _locked_project(session, tenant_id, project_id)
    folders = await _folders(session, tenant_id, project_id)
    clean = clean_name(name)
    _check_place(folders, name=clean, parent_id=parent_id)
    folder = NarrativeAssetFolder(
        tenant_id=tenant_id,
        project_id=project_id,
        parent_id=parent_id,
        name=clean,
        created_by_user_id=author_user_id,
    )
    session.add(folder)
    await session.flush()
    await session.refresh(folder)
    return folder


_UNCHANGED = object()


async def update_folder(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    folder_id: UUID,
    name: str | None,
    parent_id: UUID | None | object = _UNCHANGED,
) -> NarrativeAssetFolder:
    await _locked_project(session, tenant_id, project_id)
    folders = await _folders(session, tenant_id, project_id)
    folder = folders.get(folder_id)
    if folder is None:
        raise NotFoundError("Folder was not found.")
    clean = clean_name(name) if name is not None else folder.name
    parent = folder.parent_id if parent_id is _UNCHANGED else parent_id
    assert parent is None or isinstance(parent, UUID)
    _check_place(folders, name=clean, parent_id=parent, moving=folder)
    folder.name, folder.parent_id = clean, parent
    folder.updated_at = datetime.now(UTC)
    await session.flush()
    await session.refresh(folder)
    return folder


async def delete_folder(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, folder_id: UUID
) -> None:
    """Hand the folder's subfolders and assets to its parent, then remove it."""
    await _locked_project(session, tenant_id, project_id)
    folders = await _folders(session, tenant_id, project_id)
    folder = folders.get(folder_id)
    if folder is None:
        raise NotFoundError("Folder was not found.")
    for child in folders.values():
        if child.parent_id == folder.id:
            _check_place(
                {key: value for key, value in folders.items() if key != folder.id},
                name=child.name,
                parent_id=folder.parent_id,
                moving=child,
            )
            child.parent_id = folder.parent_id
    await session.execute(
        update(NarrativeAsset)
        .where(
            NarrativeAsset.tenant_id == tenant_id,
            NarrativeAsset.project_id == project_id,
            NarrativeAsset.folder_id == folder.id,
        )
        .values(folder_id=folder.parent_id)
    )
    await session.flush()
    await session.delete(folder)
    await session.flush()


async def move_assets(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    asset_ids: list[UUID],
    folder_id: UUID | None,
) -> list[NarrativeAsset]:
    if not 1 <= len(asset_ids) <= MOVE_LIMIT:
        raise _invalid(f"Move 1 to {MOVE_LIMIT} assets at a time.")
    await _locked_project(session, tenant_id, project_id)
    if folder_id is not None and folder_id not in await _folders(session, tenant_id, project_id):
        raise NotFoundError("Folder was not found.")
    wanted = set(asset_ids)
    assets = list(
        await session.scalars(
            select(NarrativeAsset)
            .where(
                NarrativeAsset.tenant_id == tenant_id,
                NarrativeAsset.project_id == project_id,
                NarrativeAsset.id.in_(wanted),
                NarrativeAsset.status != "discarded",
            )
            .with_for_update()
        )
    )
    if len(assets) != len(wanted):
        raise NotFoundError("Asset was not found.")
    for asset in assets:
        asset.folder_id = folder_id
    await session.flush()
    for asset in assets:
        await session.refresh(asset)
    return sorted(assets, key=lambda item: (item.name.lower(), str(item.id)))
