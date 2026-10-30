"""Editor-only character profiles and the creator's choice of portrait (ADR 0039).

Story package v1 characters carry only a name, so appearance and the chosen image
live here per project and character ID, like the scene layout. Choosing a
candidate approves it; story content, revisions and exports do not change.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.audit import AuditActor, record_audit_event
from flint_graph.application.services.narrative_projects import get_project
from flint_graph.domain.enums import AuditAction
from flint_graph.domain.errors import ConflictError, DomainError, NotFoundError
from flint_graph.infrastructure.db.models import NarrativeAsset, NarrativeCharacterProfile

Profile = tuple[NarrativeCharacterProfile, NarrativeAsset | None]


def _stale() -> DomainError:
    return DomainError(
        409,
        "Character conflict",
        "Someone else changed this character. Reload to see their changes.",
        "stale-character",
    )


async def _portraits(session: AsyncSession, ids: set[UUID]) -> dict[UUID, NarrativeAsset]:
    if not ids:
        return {}
    rows = await session.scalars(select(NarrativeAsset).where(NarrativeAsset.id.in_(ids)))
    return {asset.id: asset for asset in rows}


async def list_profiles(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID
) -> list[Profile]:
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    profiles = list(
        await session.scalars(
            select(NarrativeCharacterProfile)
            .where(
                NarrativeCharacterProfile.tenant_id == tenant_id,
                NarrativeCharacterProfile.project_id == project_id,
            )
            .order_by(NarrativeCharacterProfile.character_id)
        )
    )
    assets = await _portraits(
        session, {item.portrait_asset_id for item in profiles if item.portrait_asset_id}
    )
    return [
        (item, assets.get(item.portrait_asset_id) if item.portrait_asset_id else None)
        for item in profiles
    ]


async def _editable(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    character_id: str,
    base_version: int,
    author_user_id: UUID,
) -> NarrativeCharacterProfile:
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    if project.archived_at is not None:
        raise ConflictError("Restore this project before editing characters.")
    profile = await session.scalar(
        select(NarrativeCharacterProfile)
        .where(
            NarrativeCharacterProfile.project_id == project_id,
            NarrativeCharacterProfile.character_id == character_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (profile.version if profile is not None else 0) != base_version:
        raise _stale()
    if profile is None:
        profile = NarrativeCharacterProfile(
            project_id=project_id,
            character_id=character_id,
            tenant_id=tenant_id,
            appearance="",
            character_type="other",
            framing="portrait",
            version=0,
            updated_by_user_id=author_user_id,
        )
        session.add(profile)
    profile.version += 1
    profile.updated_by_user_id = author_user_id
    profile.updated_at = datetime.now(UTC)
    return profile


async def save_profile(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    character_id: str,
    base_version: int,
    appearance: str,
    character_type: str,
    framing: str,
    author_user_id: UUID,
) -> Profile:
    profile = await _editable(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        base_version=base_version,
        author_user_id=author_user_id,
    )
    profile.appearance, profile.character_type, profile.framing = (
        appearance,
        character_type,
        framing,
    )
    await session.flush()
    portrait = (
        await session.get(NarrativeAsset, profile.portrait_asset_id)
        if profile.portrait_asset_id
        else None
    )
    return profile, portrait


async def get_asset(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, asset_id: UUID, lock: bool = False
) -> NarrativeAsset:
    statement = select(NarrativeAsset).where(
        NarrativeAsset.tenant_id == tenant_id,
        NarrativeAsset.project_id == project_id,
        NarrativeAsset.id == asset_id,
    )
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    asset = await session.scalar(statement)
    if asset is None:
        raise NotFoundError("Image was not found.")
    return asset


async def choose_portrait(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    character_id: str,
    base_version: int,
    asset_id: UUID | None,
    author_user_id: UUID,
    actor: AuditActor,
) -> Profile:
    profile = await _editable(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        base_version=base_version,
        author_user_id=author_user_id,
    )
    asset = None
    if asset_id is not None:
        asset = await get_asset(
            session, tenant_id=tenant_id, project_id=project_id, asset_id=asset_id, lock=True
        )
        if asset.status == "discarded" or asset.kind != "character_portrait":
            raise ConflictError("This image can no longer be chosen.")
        if asset.status == "candidate":
            asset.status = "approved"
            asset.approved_by_user_id = author_user_id
            asset.approved_at = datetime.now(UTC)
    profile.portrait_asset_id = asset_id
    await session.flush()
    await record_audit_event(
        session,
        tenant_id=tenant_id,
        action=AuditAction.NARRATIVE_CHARACTER_PORTRAIT_CHOSEN,
        actor=actor,
        resource_type="narrative_character_profile",
        resource_id=None,
        metadata={
            "project_id": str(project_id),
            "character_id": character_id,
            "asset_id": str(asset_id) if asset_id else None,
        },
    )
    return profile, asset


async def discard_asset(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    asset_id: UUID,
    actor: AuditActor,
) -> NarrativeAsset:
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    if project.archived_at is not None:
        raise ConflictError("Restore this project before editing characters.")
    asset = await get_asset(
        session, tenant_id=tenant_id, project_id=project_id, asset_id=asset_id, lock=True
    )
    if asset.status == "discarded":
        return asset
    used = await session.scalar(
        select(NarrativeCharacterProfile.character_id).where(
            NarrativeCharacterProfile.project_id == project_id,
            NarrativeCharacterProfile.portrait_asset_id == asset_id,
        )
    )
    if used is not None:
        raise ConflictError("This image is a character's portrait. Choose another one first.")
    asset.status = "discarded"
    await session.flush()
    await record_audit_event(
        session,
        tenant_id=tenant_id,
        action=AuditAction.NARRATIVE_ASSET_DISCARDED,
        actor=actor,
        resource_type="narrative_asset",
        resource_id=asset.id,
        metadata={"project_id": str(project_id)},
    )
    await session.refresh(asset)
    return asset
