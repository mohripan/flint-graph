"""Creator feedback is advisory, separate from image approval and from ML scores."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.audit import AuditActor, record_audit_event
from flint_graph.application.services.narrative_characters import get_asset
from flint_graph.application.services.narrative_looks import get_look, invalid
from flint_graph.application.services.narrative_projects import get_project
from flint_graph.domain.enums import AuditAction
from flint_graph.domain.errors import ConflictError, DomainError
from flint_graph.infrastructure.db.models import NarrativeAsset
from flint_graph.infrastructure.db.narrative_look_models import (
    NarrativeCandidateReview,
    NarrativeLookJob,
)


async def review_candidate(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    character_id: str,
    look_id: UUID,
    asset_id: UUID,
) -> NarrativeAsset:
    await get_look(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        look_id=look_id,
    )
    asset = await get_asset(session, tenant_id=tenant_id, project_id=project_id, asset_id=asset_id)
    if (
        asset.status == "discarded"
        or asset.media_type != "image/png"
        or asset.kind not in ("sprite", "character_portrait", "image")
    ):
        raise invalid("Choose an available character image to compare.")
    if asset.character_id not in (None, character_id):
        job_look = (
            await session.get(NarrativeLookJob, (asset.job_id, character_id))
            if asset.job_id
            else None
        )
        if not job_look or job_look.look_id != look_id:
            raise invalid("This image belongs to another character.")
    return asset


async def read_review(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    character_id: str,
    look_id: UUID,
    asset_id: UUID,
) -> NarrativeCandidateReview | None:
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    await review_candidate(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        look_id=look_id,
        asset_id=asset_id,
    )
    return await session.get(NarrativeCandidateReview, (look_id, asset_id), populate_existing=True)


async def write_review(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    character_id: str,
    look_id: UUID,
    asset_id: UUID,
    author_user_id: UUID,
    base_version: int,
    identity: str,
    clothes: str,
    notes: str,
    actor: AuditActor,
) -> NarrativeCandidateReview:
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    if project.archived_at is not None:
        raise ConflictError("Restore this project before reviewing images.")
    asset = await review_candidate(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        look_id=look_id,
        asset_id=asset_id,
    )
    row = await session.get(NarrativeCandidateReview, (look_id, asset_id), populate_existing=True)
    if (row.version if row else 0) != base_version:
        raise DomainError(
            409,
            "Review conflict",
            "Someone else reviewed this image. Reload their feedback before saving.",
            "stale-candidate-review",
        )
    if row is None:
        look = await get_look(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=character_id,
            look_id=look_id,
        )
        row = NarrativeCandidateReview(
            look_id=look_id,
            asset_id=asset_id,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=character_id,
            source_sha256=look.source_sha256,
            candidate_sha256=asset.sha256,
            version=0,
        )
        session.add(row)
    row.identity, row.clothes, row.notes = identity, clothes, notes.strip()
    row.version += 1
    row.reviewed_by_user_id = author_user_id
    await session.flush()
    await record_audit_event(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action=AuditAction.NARRATIVE_CANDIDATE_REVIEWED,
        resource_type="narrative_asset",
        resource_id=asset_id,
        metadata={
            "project_id": str(project_id),
            "character_id": character_id,
            "look_id": str(look_id),
            "version": row.version,
        },
    )
    return row
