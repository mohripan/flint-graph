"""Treat tagger output as a suggestion; ratings and gender guesses never become tags."""

import math
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.narrative_characters import get_asset
from flint_graph.application.services.narrative_looks import invalid, reference
from flint_graph.application.services.narrative_projects import get_project
from flint_graph.domain.errors import ConflictError
from flint_graph.infrastructure.db.narrative_look_models import NarrativeLookObservation
from flint_graph.infrastructure.narrative_look_tagger import WD_MANIFEST, unavailable
from flint_graph.narrative.character_bench import CLOTHING_V1
from flint_graph.narrative.imagegen import ContentPolicy

COLORS = (
    "black blue brown green grey gray orange pink purple red silver white yellow blonde "
    "aqua multicolored two_tone gradient streaked"
).split()
TRAITS = {f"{color}_{feature}" for color in COLORS for feature in ("hair", "eyes")} | {
    "long_hair",
    "short_hair",
    "medium_hair",
    "very_long_hair",
    "ponytail",
    "low_ponytail",
    "high_ponytail",
    "braid",
    "single_braid",
    "twin_braids",
    "twintails",
    "bob_cut",
    "bangs",
    "heterochromia",
    "curly_hair",
    "wavy_hair",
    "straight_hair",
}


def validate_observation(result: dict[str, Any]) -> None:
    if result.get("model_manifest_sha256") != WD_MANIFEST or not re.fullmatch(
        r"[a-f0-9]{64}", str(result.get("tagger_sha256", ""))
    ):
        raise unavailable()
    for field in ("general_tags", "rating_tags_never_prompt"):
        probabilities = result.get(field)
        if not isinstance(probabilities, dict) or len(probabilities) > 10000:
            raise unavailable()
        if any(
            not isinstance(tag, str)
            or len(tag) > 160
            or type(value) not in (int, float)
            or not math.isfinite(value)
            or not 0 <= value <= 1
            for tag, value in probabilities.items()
        ):
            raise unavailable()


def suggested_tags(result: dict[str, Any], policy: ContentPolicy) -> tuple[list[str], list[str]]:
    identity, clothes = [], []
    for tag, confidence in result["general_tags"].items():
        if confidence < 0.35:
            continue
        text = tag.replace("_", " ")
        try:
            policy.check(text)
        except ValueError:
            continue
        if tag in TRAITS:
            identity.append(text)
        elif not tag.startswith(("no_", "removed_")) and tag.rsplit("_", 1)[-1] in CLOTHING_V1:
            clothes.append(text)
    return identity[:24], clothes[:24]


async def record_observation(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    character_id: str,
    asset_id: UUID,
    source_sha256: str,
    result: dict[str, Any],
    approved_only: bool = True,
) -> NarrativeLookObservation:
    validate_observation(result)
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    if project.archived_at is not None:
        raise ConflictError("Restore this project before reading image tags.")
    asset = (
        await reference(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=character_id,
            asset_id=asset_id,
        )
        if approved_only
        else await get_asset(session, tenant_id=tenant_id, project_id=project_id, asset_id=asset_id)
    )
    if asset.status == "discarded" or asset.media_type != "image/png":
        raise invalid("This image is no longer available for comparison.")
    if asset.sha256 != source_sha256:
        raise invalid("The approved reference changed. Choose it again.")
    existing = await session.scalar(
        select(NarrativeLookObservation).where(
            NarrativeLookObservation.asset_id == asset_id,
            NarrativeLookObservation.source_sha256 == source_sha256,
            NarrativeLookObservation.tagger_sha256 == result["tagger_sha256"],
        )
    )
    if existing:
        return existing
    row = NarrativeLookObservation(
        tenant_id=tenant_id,
        project_id=project_id,
        asset_id=asset_id,
        source_sha256=source_sha256,
        tagger_sha256=result["tagger_sha256"],
        observation=result,
    )
    session.add(row)
    await session.flush()
    return row
