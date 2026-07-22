from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.domain.enums import SourceType
from flint_graph.domain.errors import ConflictError, NotFoundError
from flint_graph.infrastructure.db.models import Document


async def create_document(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    title: str,
    source_type: SourceType,
    source_uri: str | None,
    external_id: str | None,
) -> Document:
    document = Document(
        tenant_id=tenant_id,
        title=title,
        source_type=source_type,
        source_uri=source_uri,
        external_id=external_id,
    )
    try:
        async with session.begin_nested():
            session.add(document)
            await session.flush()
    except IntegrityError as exc:
        raise ConflictError(
            "A document with this external_id already exists for the tenant."
        ) from exc
    await session.refresh(document)
    return document

async def get_document(session: AsyncSession, *, tenant_id: UUID, document_id: UUID) -> Document:
    document = await session.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
    )
    if document is None:
        raise NotFoundError(f"Document: '{document_id}' was not found.")
    return document