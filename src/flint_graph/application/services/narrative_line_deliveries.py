"""Per-line delivery overrides: editor metadata for voice generation (#177, ADR 0045).

A line's delivery defaults in the Studio from its sprite expression; an override is
stored here, outside the story, because the runtimes play clips and never speak.
What a clip was actually generated with is recorded in its provenance.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.narrative_projects import get_project
from flint_graph.domain.errors import ConflictError, DomainError
from flint_graph.infrastructure.db.models import NarrativeLineDelivery
from flint_graph.narrative.voice_models import DELIVERIES, MODELS


def _clean(emotion: str, intensity: float, tag: str | None) -> tuple[str, float, str | None]:
    tags = {tag for spec in MODELS.values() for tag in spec.tags}
    if (
        emotion not in DELIVERIES
        or not 0 <= intensity <= 1
        or (tag is not None and tag not in tags)
    ):
        raise DomainError(
            422, "Invalid delivery", "Choose a listed delivery and sound.", "invalid-delivery"
        )
    return emotion, round(intensity, 2), tag


async def list_deliveries(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID
) -> list[NarrativeLineDelivery]:
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    return list(
        await session.scalars(
            select(NarrativeLineDelivery)
            .where(
                NarrativeLineDelivery.tenant_id == tenant_id,
                NarrativeLineDelivery.project_id == project_id,
            )
            .order_by(NarrativeLineDelivery.node_id)
        )
    )


async def set_delivery(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    node_id: str,
    emotion: str,
    intensity: float,
    tag: str | None,
    user_id: UUID,
) -> NarrativeLineDelivery:
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    if project.archived_at is not None:
        raise ConflictError("Restore this project before changing it.")
    emotion, intensity, tag = _clean(emotion, intensity, tag)
    row = await session.get(NarrativeLineDelivery, (project_id, node_id))
    if row is None:
        row = NarrativeLineDelivery(project_id=project_id, node_id=node_id, tenant_id=tenant_id)
        session.add(row)
    row.emotion, row.intensity, row.tag, row.updated_by_user_id = emotion, intensity, tag, user_id
    await session.flush()
    return row


async def clear_delivery(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, node_id: str
) -> None:
    await get_project(session, tenant_id=tenant_id, project_id=project_id, for_update=True)
    row = await session.get(NarrativeLineDelivery, (project_id, node_id))
    if row is not None and row.tenant_id == tenant_id:
        await session.delete(row)
        await session.flush()
