"""Approved same-look datasets and immutable adapter compatibility checks."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.narrative_looks import get_look, look_snapshot, reference
from flint_graph.domain.errors import DomainError
from flint_graph.infrastructure.db.narrative_character_adapter_models import (
    NarrativeCharacterAdapter,
)
from flint_graph.infrastructure.db.narrative_look_models import NarrativeCharacterLook
from flint_graph.infrastructure.db.narrative_style_models import NarrativeStyleJob


def invalid(detail: str) -> DomainError:
    return DomainError(422, "Invalid character training set", detail, "invalid-character-adapter")


async def training_look(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    target: dict[str, Any],
    images: list[dict[str, Any]],
) -> NarrativeCharacterLook:
    if target["same_look_confirmed"] is not True:
        raise invalid("Confirm that every selected image shows this character and outfit.")
    if target["anatomy_reviewed"] is not True:
        raise invalid(
            "Review anatomy, hands, feet and limb count in every selected image before training."
        )
    look = await get_look(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=target["character_id"],
        look_id=UUID(str(target["look_id"])),
    )
    base = await reference(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=look.character_id,
        asset_id=look.asset_id,
    )
    if base.sha256 != look.source_sha256:
        raise invalid("The approved base no longer matches this reviewed look.")
    hashes = set()
    for image in images:
        asset = await reference(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=look.character_id,
            asset_id=UUID(str(image["asset_id"])),
        )
        hashes.add(asset.sha256)
    if look.source_sha256 not in hashes:
        raise invalid("Include this look's approved base image in the training set.")
    return look


async def details(session: AsyncSession, job: NarrativeStyleJob) -> dict[str, Any]:
    target = await session.get(NarrativeCharacterAdapter, job.id)
    return {
        "kind": "character_look" if target else "project_style",
        "look": target.snapshot if target else None,
    }


async def verify_target(
    session: AsyncSession,
    job: NarrativeStyleJob,
    *,
    character_id: str | None = None,
    look_id: UUID | None = None,
) -> NarrativeCharacterAdapter | None:
    target = await session.get(NarrativeCharacterAdapter, job.id)
    if target is None:
        return None
    if (
        target.project_id != job.project_id
        or target.tenant_id != job.tenant_id
        or (character_id is not None and target.character_id != character_id)
        or (look_id is not None and target.look_id != look_id)
    ):
        raise invalid("Choose a trained version for this exact reviewed character look.")
    look = await get_look(
        session,
        tenant_id=job.tenant_id,
        project_id=job.project_id,
        character_id=target.character_id,
        look_id=target.look_id,
    )
    if look_snapshot(look) != target.snapshot:
        raise invalid("The reviewed look no longer matches this training version.")
    base = await reference(
        session,
        tenant_id=job.tenant_id,
        project_id=job.project_id,
        character_id=target.character_id,
        asset_id=look.asset_id,
    )
    if base.sha256 != target.snapshot["source_sha256"]:
        raise invalid("The approved base is unavailable.")
    return target


async def list_details(
    session: AsyncSession, jobs: list[NarrativeStyleJob]
) -> dict[UUID, dict[str, Any]]:
    result: dict[UUID, dict[str, Any]] = {
        job.id: {"kind": "project_style", "look": None} for job in jobs
    }
    if not jobs:
        return result
    targets = await session.scalars(
        select(NarrativeCharacterAdapter).where(
            NarrativeCharacterAdapter.job_id.in_([job.id for job in jobs])
        )
    )
    for target in targets:
        result[target.job_id] = {"kind": "character_look", "look": target.snapshot}
    return result
