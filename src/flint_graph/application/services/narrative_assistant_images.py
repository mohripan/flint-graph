"""Screenshots attached to a message to the assistant (ADR 0076).

They are private to the project, never part of a story or a game, and deleted with the project.
"""

from __future__ import annotations

import hashlib
import logging
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flint_graph.application.services.narrative_projects import get_project
from flint_graph.domain.errors import ConflictError, DomainError, NotFoundError
from flint_graph.infrastructure.db.models import NarrativeAssistantImage
from flint_graph.infrastructure.narrative_artifact_store import assistant_image_object_key
from flint_graph.narrative.assistant.context import screenshot_line
from flint_graph.narrative.png import normalize_png, validate_png
from flint_graph.narrative.values import PackageError
from flint_graph.prompts.source import render

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGES_PER_MESSAGE = 3
# Far more than anyone needs, and it keeps one person from filling the bucket.
MAX_IMAGES_PER_PROJECT = 500
_DESCRIPTION_CHARS = 1200
_REQUEST_CHARS = 1000


class ImageStore(Protocol):
    async def put_once(
        self, key: str, data: bytes, *, expected_sha256: str, content_type: str, max_bytes: int
    ) -> Any: ...

    async def get_verified(
        self, key: str, *, expected_size: int, expected_sha256: str, max_bytes: int
    ) -> bytes: ...


class Describer(Protocol):
    async def describe(self, png: bytes, prompt: str) -> str: ...


class Observer(Protocol):
    async def step(self, name: str, state: str, detail: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class TurnImage:
    id: UUID
    sha256: str
    size_bytes: int
    description: str | None


async def add_image(
    session: AsyncSession,
    *,
    store: ImageStore,
    tenant_id: UUID,
    project_id: UUID,
    user_id: UUID,
    data: bytes,
) -> NarrativeAssistantImage:
    """Keep a pasted picture. The same picture pasted again is the same row."""
    project = await get_project(session, tenant_id=tenant_id, project_id=project_id)
    if project.archived_at is not None:
        raise ConflictError("Restore this project from the trash before attaching pictures.")
    try:
        clean = normalize_png(data, "image")
        validate_png(clean, "image")
    except PackageError:
        raise DomainError(
            422,
            "Invalid picture",
            "That picture could not be read. Try pasting it again, or save it as a PNG.",
            "invalid-picture",
        ) from None
    sha256 = hashlib.sha256(clean).hexdigest()
    mine = (
        NarrativeAssistantImage.tenant_id == tenant_id,
        NarrativeAssistantImage.project_id == project_id,
    )
    existing = await session.scalar(
        select(NarrativeAssistantImage).where(*mine, NarrativeAssistantImage.sha256 == sha256)
    )
    if existing is not None:
        return existing
    count = await session.scalar(
        select(func.count()).select_from(NarrativeAssistantImage).where(*mine)
    )
    if int(count or 0) >= MAX_IMAGES_PER_PROJECT:
        raise ConflictError("This project has too many attached pictures.")
    # validate_png has checked the header, so these offsets are the real size.
    width, height = struct.unpack(">II", clean[16:24])
    image_id = uuid4()
    await store.put_once(
        assistant_image_object_key(tenant_id=tenant_id, project_id=project_id, image_id=image_id),
        clean,
        expected_sha256=sha256,
        content_type="image/png",
        max_bytes=MAX_IMAGE_BYTES,
    )
    row = NarrativeAssistantImage(
        id=image_id,
        tenant_id=tenant_id,
        project_id=project_id,
        uploaded_by_user_id=user_id,
        sha256=sha256,
        size_bytes=len(clean),
        width=width,
        height=height,
    )
    session.add(row)
    await session.flush()
    return row


async def get_image(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, image_id: UUID
) -> NarrativeAssistantImage:
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    row = await session.scalar(
        select(NarrativeAssistantImage).where(
            NarrativeAssistantImage.tenant_id == tenant_id,
            NarrativeAssistantImage.project_id == project_id,
            NarrativeAssistantImage.id == image_id,
        )
    )
    if row is None:
        raise NotFoundError("That picture was not found.")
    return row


async def turn_images(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    attachments: Sequence[dict[str, Any]],
) -> tuple[TurnImage, ...]:
    """The pictures on a message, in the order they were attached."""
    wanted = [UUID(item["id"]) for item in attachments if item.get("kind") == "image"]
    if not wanted:
        return ()
    rows = {
        row.id: row
        for row in await session.scalars(
            select(NarrativeAssistantImage).where(
                NarrativeAssistantImage.tenant_id == tenant_id,
                NarrativeAssistantImage.project_id == project_id,
                NarrativeAssistantImage.id.in_(wanted),
            )
        )
    }
    return tuple(
        TurnImage(row.id, row.sha256, row.size_bytes, row.description)
        for row in (rows.get(item) for item in wanted)
        if row is not None
    )


async def describe_attached(
    factory: async_sessionmaker[AsyncSession],
    *,
    store: ImageStore | None,
    vision: Describer | None,
    tenant_id: UUID,
    project_id: UUID,
    images: Sequence[TurnImage],
    request: str,
    observer: Observer | None = None,
) -> tuple[str, ...]:
    """Look at each picture once, and say in words what it shows.

    A picture that cannot be read never stops the reply. The assistant is told, so it can say so.
    """
    if observer is not None:
        await observer.step("looking", "started", {"pictures": len(images)})
    lines = []
    for image in images:
        description = image.description
        if description is None and vision is not None and store is not None:
            try:
                png = await store.get_verified(
                    assistant_image_object_key(
                        tenant_id=tenant_id, project_id=project_id, image_id=image.id
                    ),
                    expected_size=image.size_bytes,
                    expected_sha256=image.sha256,
                    max_bytes=MAX_IMAGE_BYTES,
                )
                prompt = render(
                    "narrative.assistant.describe_image", request=request[:_REQUEST_CHARS]
                )
                description = (await vision.describe(png, prompt))[:_DESCRIPTION_CHARS]
                async with factory() as session:
                    row = await session.get(NarrativeAssistantImage, image.id)
                    if row is not None:
                        row.description = description
                        await session.commit()
            except Exception as error:
                # The type only: a provider's message could quote the prompt.
                logger.warning("attached picture not read: %s", type(error).__name__)
                description = None
        lines.append(screenshot_line(description))
    if observer is not None:
        await observer.step("looking", "done", {"pictures": len(images)})
    return tuple(lines)
