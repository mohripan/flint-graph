from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.query_scope import missing_financial_scope
from flint_graph.domain.enums import DocumentIndexCoverageStatus, DocumentVersionStatus
from flint_graph.infrastructure.db.models import Document, DocumentIndexCoverage, DocumentVersion


@dataclass(frozen=True, slots=True)
class FinancialScopeClarification:
    text: str
    missing_scope: list[str]


async def financial_scope_clarification(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    retrieval_index_version_id: UUID,
    query: str,
    filters: dict[str, Any],
) -> FinancialScopeClarification | None:
    missing = missing_financial_scope(query)
    if not missing:
        return None
    statement = (
        select(Document.id)
        .distinct()
        .join(DocumentVersion, DocumentVersion.document_id == Document.id)
        .join(
            DocumentIndexCoverage, DocumentIndexCoverage.document_version_id == DocumentVersion.id
        )
        .where(
            Document.tenant_id == tenant_id,
            Document.deleted_at.is_(None),
            DocumentVersion.status == DocumentVersionStatus.ACTIVE,
            DocumentIndexCoverage.tenant_id == tenant_id,
            DocumentIndexCoverage.document_id == Document.id,
            DocumentIndexCoverage.retrieval_index_version_id == retrieval_index_version_id,
            DocumentIndexCoverage.status == DocumentIndexCoverageStatus.COMPLETED,
        )
        .limit(2)
    )
    for name, column in [("document_id", Document.id), ("document_version_id", DocumentVersion.id)]:
        if name in filters:
            try:
                identifier = UUID(str(filters[name]))
            except ValueError:
                continue  # A malformed selector cannot grant a scope exemption.
            statement = statement.where(column == identifier)
    if len(list(await session.scalars(statement))) < 2:
        return None
    text = (
        "Which company or document should I use, and for which reporting period?"
        if "reporting_period" in missing
        else "Which company or document should I use for that reporting period?"
    )
    return FinancialScopeClarification(text=text, missing_scope=missing)
