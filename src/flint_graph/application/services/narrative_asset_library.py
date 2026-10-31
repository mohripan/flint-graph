"""Project asset library: creator uploads with a rights declaration (ADR 0040).

Uploads are inspected before anything is stored: images must pass the strict PNG
validator (alpha kept) and fonts the bounded sfnt checks. The uploader declares the
right to use the file; that declaration is recorded, never treated as verified
ownership. Generated images arrive through image jobs as candidates instead.
"""

import asyncio
import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.narrative_characters import get_asset
from flint_graph.application.services.narrative_projects import get_project
from flint_graph.domain.errors import ConflictError, DomainError, NotFoundError
from flint_graph.infrastructure.db.models import NarrativeAsset
from flint_graph.narrative.font import FONT_LIMIT, validate_font
from flint_graph.narrative.png import normalize_png, validate_png
from flint_graph.narrative.values import PackageError

IMAGE_KINDS = ("background", "sprite", "image")
UPLOAD_KINDS = (*IMAGE_KINDS, "font")
IMAGE_LIMIT = 10 * 1024 * 1024


_FONT_PROBLEMS = {
    "invalid_font": "This file is not a TrueType or OpenType font.",
    "font_variable": (
        "Variable fonts are not supported yet. Upload a static TTF or OTF; Google Fonts "
        "downloads include them in the static folder."
    ),
    "font_embedding_restricted": "This font's license does not allow embedding it in a game.",
}


def _invalid(detail: str) -> DomainError:
    return DomainError(422, "Invalid asset", detail, "invalid-asset")


@dataclass(frozen=True)
class Upload:
    kind: str
    media_type: str
    data: bytes
    sha256: str
    width: int | None
    height: int | None


def inspect_upload(kind: str, data: bytes) -> Upload:
    """Validate an upload for its kind; nothing is stored before this passes."""
    if kind not in UPLOAD_KINDS:
        raise _invalid("Choose background, sprite, image or font.")
    if kind == "font":
        try:
            flavor = validate_font(data, "file")
        except PackageError as error:
            raise _invalid(_FONT_PROBLEMS.get(error.code, _FONT_PROBLEMS["invalid_font"])) from None
        media, width, height = f"font/{flavor}", None, None
    else:
        if len(data) > IMAGE_LIMIT:
            raise _invalid("Images can be at most 10 MiB.")
        try:
            # Editors add text, time and colour-profile chunks; drop them losslessly.
            data = normalize_png(data, "file")
            validate_png(data, "file")
        except PackageError:
            raise _invalid("Upload a PNG image (transparency is kept).") from None
        width, height = struct.unpack(">II", data[16:24])
        media = "image/png"
    return Upload(kind, media, data, sha256(data).hexdigest(), width, height)


def upload_limit(kind: str) -> int:
    return FONT_LIMIT if kind == "font" else IMAGE_LIMIT


# Decompressing a large PNG costs CPU and up to ~128 MiB; keep it off the event loop
# and bound how many run at once in one API process.
_INSPECTIONS = asyncio.Semaphore(2)


async def inspect_upload_bounded(kind: str, data: bytes) -> Upload:
    async with _INSPECTIONS:
        return await asyncio.to_thread(inspect_upload, kind, data)


async def find_duplicate(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, upload: Upload
) -> NarrativeAsset | None:
    """The live asset with these exact bytes, or a conflict if it has another kind."""
    existing = await session.scalar(
        select(NarrativeAsset).where(
            NarrativeAsset.tenant_id == tenant_id,
            NarrativeAsset.project_id == project_id,
            NarrativeAsset.sha256 == upload.sha256,
            NarrativeAsset.status != "discarded",
        )
    )
    if existing is not None and existing.kind != upload.kind:
        raise ConflictError(f"This file is already in the library as “{existing.name}”.")
    return existing


async def check_uploadable(session: AsyncSession, *, tenant_id: UUID, project_id: UUID) -> None:
    project = await get_project(session, tenant_id=tenant_id, project_id=project_id)
    if project.archived_at is not None:
        raise ConflictError("Restore this project before adding assets.")


async def record_upload(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    asset_id: UUID,
    upload: Upload,
    name: str,
    license: str,
    notice: str,
    author_user_id: UUID,
) -> NarrativeAsset:
    """Persist an upload whose bytes were already stored create-only and verified."""
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    if project.archived_at is not None:
        raise ConflictError("Restore this project before adding assets.")
    now = datetime.now(UTC)
    asset = NarrativeAsset(
        id=asset_id,
        tenant_id=tenant_id,
        project_id=project_id,
        kind=upload.kind,
        source="uploaded",
        name=name,
        media_type=upload.media_type,
        sha256=upload.sha256,
        size_bytes=len(upload.data),
        width=upload.width,
        height=upload.height,
        provenance={"source": "upload"},
        license=license,
        notice=notice or None,
        rights_declared_by_user_id=author_user_id,
        rights_declared_at=now,
        status="approved",
        created_by_user_id=author_user_id,
        approved_by_user_id=author_user_id,
        approved_at=now,
        # Microsecond time keeps "newest first" stable even where now() has 1 s resolution.
        created_at=now,
    )
    session.add(asset)
    await session.flush()
    await session.refresh(asset)
    return asset


async def list_assets(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    kind: str | None,
    status: str | None,
    limit: int,
    before: UUID | None,
) -> list[NarrativeAsset]:
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    scope = [NarrativeAsset.tenant_id == tenant_id, NarrativeAsset.project_id == project_id]
    if kind is not None:
        scope.append(NarrativeAsset.kind == kind)
    scope.append(
        NarrativeAsset.status == status
        if status is not None
        else NarrativeAsset.status != "discarded"
    )
    statement = select(NarrativeAsset).where(*scope)
    if before is not None:
        cursor = await session.scalar(
            select(NarrativeAsset).where(
                NarrativeAsset.tenant_id == tenant_id,
                NarrativeAsset.project_id == project_id,
                NarrativeAsset.id == before,
            )
        )
        if cursor is None:
            raise NotFoundError("Asset cursor was not found.")
        statement = statement.where(
            (NarrativeAsset.created_at < cursor.created_at)
            | ((NarrativeAsset.created_at == cursor.created_at) & (NarrativeAsset.id < cursor.id))
        )
    statement = statement.order_by(NarrativeAsset.created_at.desc(), NarrativeAsset.id.desc())
    return list(await session.scalars(statement.limit(limit)))


async def _editable(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, asset_id: UUID
) -> NarrativeAsset:
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    if project.archived_at is not None:
        raise ConflictError("Restore this project before changing assets.")
    return await get_asset(
        session, tenant_id=tenant_id, project_id=project_id, asset_id=asset_id, lock=True
    )


async def rename_asset(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, asset_id: UUID, name: str
) -> NarrativeAsset:
    asset = await _editable(session, tenant_id=tenant_id, project_id=project_id, asset_id=asset_id)
    asset.name = name
    await session.flush()
    await session.refresh(asset)
    return asset


async def approve_asset(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    asset_id: UUID,
    author_user_id: UUID,
) -> NarrativeAsset:
    asset = await _editable(session, tenant_id=tenant_id, project_id=project_id, asset_id=asset_id)
    if asset.status == "discarded":
        raise ConflictError("A discarded asset cannot be approved.")
    if asset.status == "candidate":
        asset.status = "approved"
        asset.approved_by_user_id = author_user_id
        asset.approved_at = datetime.now(UTC)
        await session.flush()
        await session.refresh(asset)
    return asset
