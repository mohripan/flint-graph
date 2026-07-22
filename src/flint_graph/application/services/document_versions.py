from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.document_lifecycle import record_superseded_version_cleanup
from flint_graph.domain.enums import DocumentVersionStatus
from flint_graph.domain.errors import ConflictError, NotFoundError
from flint_graph.infrastructure.db.models import Document, DocumentVersion


async def activate_document_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version_id: UUID,
) -> DocumentVersion:
    version = await _get_version_for_update(session, tenant_id=tenant_id, version_id=version_id)
    if version.status == DocumentVersionStatus.ACTIVE:
        return version
    _ensure_pending(version)

    active_versions = list(
        await session.scalars(
            select(DocumentVersion)
            .where(
                DocumentVersion.document_id == version.document_id,
                DocumentVersion.status == DocumentVersionStatus.ACTIVE,
                DocumentVersion.id != version.id,
            )
            .with_for_update()
        )
    )
    for active_version in active_versions:
        active_version.status = DocumentVersionStatus.SUPERSEDED

    version.status = DocumentVersionStatus.ACTIVE
    if active_versions:
        await record_superseded_version_cleanup(
            session,
            tenant_id=tenant_id,
            superseded_versions=active_versions,
        )
    await session.flush()
    return version


async def fail_document_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version_id: UUID,
) -> DocumentVersion:
    version = await _get_version_for_update(session, tenant_id=tenant_id, version_id=version_id)
    if version.status == DocumentVersionStatus.FAILED:
        return version
    _ensure_pending(version)
    version.status = DocumentVersionStatus.FAILED
    await session.flush()
    return version


async def cancel_document_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version_id: UUID,
) -> DocumentVersion:
    version = await _get_version_for_update(session, tenant_id=tenant_id, version_id=version_id)
    if version.status == DocumentVersionStatus.CANCELLED:
        return version
    _ensure_pending(version)
    version.status = DocumentVersionStatus.CANCELLED
    await session.flush()
    return version


async def _get_version_for_update(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version_id: UUID,
) -> DocumentVersion:
    version = await session.scalar(
        select(DocumentVersion)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(DocumentVersion.id == version_id, Document.tenant_id == tenant_id)
        .with_for_update()
    )
    if version is None:
        raise NotFoundError(f"Document version '{version_id}' was not found.")
    return version


def _ensure_pending(version: DocumentVersion) -> None:
    if version.status != DocumentVersionStatus.PENDING:
        raise ConflictError(
            f"Cannot change document version '{version.id}' from "
            f"'{version.status}' after it has reached a terminal state."
        )
