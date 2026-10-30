"""Shared editor-only scene hierarchy with optimistic versions.

The layout only orders and groups scene references for the Studio. It never
changes story content, revisions, packages or exports, and it tolerates scenes
that were added or removed since it was saved.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.narrative_projects import get_project
from flint_graph.domain.errors import ConflictError, DomainError
from flint_graph.infrastructure.db.models import NarrativeProjectLayout


async def get_layout(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, include_archived: bool = False
) -> tuple[int, list[dict[str, Any]]]:
    await get_project(
        session, tenant_id=tenant_id, project_id=project_id, include_archived=include_archived
    )
    row = await session.scalar(
        select(NarrativeProjectLayout).where(
            NarrativeProjectLayout.project_id == project_id,
            NarrativeProjectLayout.tenant_id == tenant_id,
        )
    )
    return (row.version, row.items) if row is not None else (0, [])


async def save_layout(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    base_version: int,
    items: list[dict[str, Any]],
    user_id: UUID,
) -> NarrativeProjectLayout:
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    if project.archived_at is not None:
        raise ConflictError("Restore this project before reorganizing its scenes.")
    row = await session.scalar(
        select(NarrativeProjectLayout)
        .where(
            NarrativeProjectLayout.project_id == project_id,
            NarrativeProjectLayout.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    if base_version != (row.version if row is not None else 0):
        raise DomainError(
            409,
            "Layout conflict",
            "The scene layout changed elsewhere. Reload it before saving again.",
            "stale-layout",
        )
    if row is None:
        row = NarrativeProjectLayout(
            project_id=project_id,
            tenant_id=tenant_id,
            version=1,
            items=items,
            updated_by_user_id=user_id,
        )
        session.add(row)
    else:
        row.version += 1
        row.items = items
        row.updated_by_user_id = user_id
    await session.flush()
    return row
