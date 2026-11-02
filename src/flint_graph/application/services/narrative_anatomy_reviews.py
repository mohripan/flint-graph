"""Keep images explicitly marked anatomically flawed out of new training."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.domain.errors import DomainError
from flint_graph.infrastructure.db.models import NarrativeAsset
from flint_graph.infrastructure.db.narrative_look_models import NarrativeAnatomyReview


async def write_anatomy(
    session: AsyncSession,
    *,
    asset: NarrativeAsset,
    anatomy: str,
    base_version: int | None,
    author_user_id: UUID,
) -> NarrativeAnatomyReview:
    """Caller holds the project lock shared with training publication and other reviews."""
    if anatomy not in {"acceptable", "flawed", "unknown"} or base_version is None:
        raise DomainError(
            422,
            "Invalid anatomy review",
            "Choose an anatomy verdict and its current version.",
            "invalid-anatomy-review",
        )
    row = await session.get(
        NarrativeAnatomyReview,
        (asset.tenant_id, asset.project_id, asset.sha256),
        populate_existing=True,
    )
    if (row.version if row else 0) != base_version:
        raise DomainError(
            409,
            "Anatomy review conflict",
            "Someone else reviewed these image bytes. Reload their feedback before saving.",
            "stale-anatomy-review",
        )
    if row and row.anatomy == anatomy:
        return row
    if row is None:
        row = NarrativeAnatomyReview(
            tenant_id=asset.tenant_id, project_id=asset.project_id, sha256=asset.sha256, version=0
        )
        session.add(row)
    row.anatomy = anatomy
    row.version += 1
    row.reviewed_by_user_id = author_user_id
    await session.flush()
    return row


async def ensure_training_anatomy(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, hashes: list[str]
) -> None:
    failed = await session.scalar(
        select(NarrativeAnatomyReview.sha256)
        .where(
            NarrativeAnatomyReview.tenant_id == tenant_id,
            NarrativeAnatomyReview.project_id == project_id,
            NarrativeAnatomyReview.sha256.in_(hashes),
            NarrativeAnatomyReview.anatomy == "flawed",
        )
        .limit(1)
    )
    if failed is not None:
        raise DomainError(
            422,
            "Training source needs review",
            "A selected image has a recorded anatomy problem. Remove it from training "
            "or revise its anatomy review after inspecting it again.",
            "anatomy-review-failed",
        )
