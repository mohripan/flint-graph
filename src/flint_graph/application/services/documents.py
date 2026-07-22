from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.domain.enums import DocumentVersionStatus, SourceType
from flint_graph.domain.errors import ConflictError, NotFoundError
from flint_graph.infrastructure.db.models import Document, DocumentVersion


@dataclass(frozen=True, slots=True)
class DocumentListItem:
    id: UUID
    tenant_id: UUID
    title: str
    source_type: SourceType
    source_uri: str | None
    external_id: str | None
    deleted_at: datetime | None
    latest_version_id: UUID | None
    latest_version_number: int | None
    latest_version_status: DocumentVersionStatus | None
    created_at: datetime
    updated_at: datetime


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


async def list_documents(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    limit: int = 100,
) -> list[DocumentListItem]:
    documents = list(
        await session.scalars(
            select(Document)
            .where(Document.tenant_id == tenant_id)
            .order_by(Document.created_at.desc(), Document.id)
            .limit(limit)
        )
    )
    items: list[DocumentListItem] = []
    for document in documents:
        latest = await session.scalar(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.version_number.desc(), DocumentVersion.created_at.desc())
            .limit(1)
        )
        items.append(
            DocumentListItem(
                id=document.id,
                tenant_id=document.tenant_id,
                title=document.title,
                source_type=document.source_type,
                source_uri=document.source_uri,
                external_id=document.external_id,
                deleted_at=document.deleted_at,
                latest_version_id=latest.id if latest is not None else None,
                latest_version_number=latest.version_number if latest is not None else None,
                latest_version_status=latest.status if latest is not None else None,
                created_at=document.created_at,
                updated_at=document.updated_at,
            )
        )
    return items
