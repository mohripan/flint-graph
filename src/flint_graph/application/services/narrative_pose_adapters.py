"""Resolve the bounded private adapter roles without changing legacy pose bindings."""

from math import isfinite
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.narrative_character_adapters import details, verify_target
from flint_graph.application.services.narrative_styles import get_style
from flint_graph.domain.errors import DomainError
from flint_graph.infrastructure.db.narrative_style_models import NarrativeStyleJob


async def resolve_adapters(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    character_id: str,
    look_id: UUID,
    model_hash: str,
    enabled: bool,
    style_input: dict[str, Any] | None,
    character_input: dict[str, Any] | None,
) -> tuple[NarrativeStyleJob | None, NarrativeStyleJob | None]:
    if (style_input or character_input) and not enabled:
        raise DomainError(
            503,
            "Adapters unavailable",
            "Trained adapters are not enabled on this server.",
            "style-unavailable",
        )
    inputs = [item for item in (character_input, style_input) if item]
    strengths = [item["strength"] for item in inputs]
    if any(
        type(value) not in (float, int) or not isfinite(value) or not 0.1 <= value <= 1
        for value in strengths
    ) or (character_input and style_input and sum(strengths) > 1 + 1e-9):
        raise DomainError(
            422,
            "Invalid strength",
            "Use strengths from 0.1 to 1; combined strengths must total at most 1.",
            "invalid-style-adapter",
        )
    if character_input and style_input and str(character_input["id"]) == str(style_input["id"]):
        raise DomainError(
            422,
            "Duplicate adapter",
            "Choose one character version and a different project style.",
            "invalid-style-adapter",
        )
    resolved: list[NarrativeStyleJob | None] = []
    for role, value in (("character", character_input), ("style", style_input)):
        if not value:
            resolved.append(None)
            continue
        job = await get_style(
            session, tenant_id=tenant_id, project_id=project_id, job_id=UUID(str(value["id"]))
        )
        if (
            job.status != "completed"
            or not job.weights_sha256
            or job.model_manifest_sha256 != model_hash
        ):
            raise DomainError(
                422,
                "Adapter unavailable",
                "Choose a completed version for this installed model.",
                "invalid-style-adapter",
            )
        target = await details(session, job)
        if character_input and target["kind"] != (
            "character_look" if role == "character" else "project_style"
        ):
            raise DomainError(
                422,
                "Wrong adapter role",
                "Choose a character version for Character and a project style for Style.",
                "invalid-style-adapter",
            )
        await verify_target(session, job, character_id=character_id, look_id=look_id)
        resolved.append(job)
    return resolved[0], resolved[1]
