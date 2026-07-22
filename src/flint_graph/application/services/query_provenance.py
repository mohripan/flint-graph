from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.query_runs import get_query_run
from flint_graph.domain.enums import DocumentVersionStatus
from flint_graph.domain.errors import NotFoundError
from flint_graph.infrastructure.db.models import (
    Document,
    DocumentVersion,
    QueryAnswerClaim,
    QueryContextPack,
    QueryContextPackRecord,
)


@dataclass(frozen=True, slots=True)
class QueryCitationClaimProvenance:
    claim_index: int
    text: str
    support_status: str
    support_score: float
    support_reason: str
    method: str


@dataclass(frozen=True, slots=True)
class QueryCitationProvenance:
    query_run_id: UUID
    tenant_id: UUID
    citation_id: str
    context_id: str
    candidate_id: str
    text: str
    token_count: int
    source_ids: dict[str, str]
    metadata: dict[str, Any]
    source_document_id: UUID | None
    source_document_version_id: UUID | None
    source_document_version_status: DocumentVersionStatus | None
    source_active: bool | None
    claims: list[QueryCitationClaimProvenance] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class QueryAnswerClaimProvenance:
    claim_index: int
    text: str
    citation_ids: list[str]
    support_status: str
    support_score: float
    support_reason: str
    method: str
    citations: list[QueryCitationProvenance]


@dataclass(frozen=True, slots=True)
class QueryAnswerProvenance:
    query_run_id: UUID
    tenant_id: UUID
    answer_text: str | None
    answer_citations: list[dict[str, Any]]
    abstained: bool
    abstain_reason: str | None
    supported_claim_count: int
    unsupported_claim_count: int
    support_method: str | None
    answer_provider: str | None
    claims: list[QueryAnswerClaimProvenance]
    citations: list[QueryCitationProvenance]


@dataclass(frozen=True, slots=True)
class _CitationSourceState:
    document_id: UUID | None
    document_version_id: UUID | None
    document_version_status: DocumentVersionStatus | None
    active: bool | None


async def get_query_answer_provenance(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
) -> QueryAnswerProvenance:
    run = await get_query_run(session, tenant_id=tenant_id, query_run_id=query_run_id)
    claims = await _load_answer_claims(
        session,
        tenant_id=tenant_id,
        query_run_id=query_run_id,
    )
    records_by_citation = await _load_context_records_by_citation(
        session,
        tenant_id=tenant_id,
        query_run_id=query_run_id,
    )
    source_states = await _load_context_source_states(
        session,
        tenant_id=tenant_id,
        records=list(records_by_citation.values()),
    )
    claim_summaries_by_citation = _claim_summaries_by_citation(claims)

    claim_rows = [
        QueryAnswerClaimProvenance(
            claim_index=claim.claim_index,
            text=claim.text,
            citation_ids=list(claim.citation_ids),
            support_status=claim.support_status,
            support_score=claim.support_score,
            support_reason=claim.support_reason,
            method=claim.method,
            citations=[
                _citation_provenance(
                    query_run_id=query_run_id,
                    tenant_id=tenant_id,
                    record=records_by_citation[citation_id],
                    source_state=source_states.get(records_by_citation[citation_id].id),
                    claims=claim_summaries_by_citation.get(citation_id, []),
                )
                for citation_id in claim.citation_ids
                if citation_id in records_by_citation
            ],
        )
        for claim in claims
    ]
    citation_ids = _ordered_unique(
        citation_id
        for claim in claims
        for citation_id in claim.citation_ids
        if citation_id in records_by_citation
    )
    citations = [
        _citation_provenance(
            query_run_id=query_run_id,
            tenant_id=tenant_id,
            record=records_by_citation[citation_id],
            source_state=source_states.get(records_by_citation[citation_id].id),
            claims=claim_summaries_by_citation.get(citation_id, []),
        )
        for citation_id in citation_ids
    ]
    return QueryAnswerProvenance(
        query_run_id=run.id,
        tenant_id=run.tenant_id,
        answer_text=run.answer_text,
        answer_citations=list(run.answer_citations),
        abstained=run.abstained,
        abstain_reason=run.abstain_reason,
        supported_claim_count=run.supported_claim_count,
        unsupported_claim_count=run.unsupported_claim_count,
        support_method=run.support_method,
        answer_provider=run.answer_provider,
        claims=claim_rows,
        citations=citations,
    )


async def get_query_citation_provenance(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
    citation_id: str,
) -> QueryCitationProvenance:
    await get_query_run(session, tenant_id=tenant_id, query_run_id=query_run_id)
    records_by_citation = await _load_context_records_by_citation(
        session,
        tenant_id=tenant_id,
        query_run_id=query_run_id,
    )
    record = records_by_citation.get(citation_id)
    if record is None:
        raise NotFoundError(
            f"Citation '{citation_id}' was not found for query run '{query_run_id}'."
        )
    claims = await _load_answer_claims(
        session,
        tenant_id=tenant_id,
        query_run_id=query_run_id,
    )
    source_states = await _load_context_source_states(
        session,
        tenant_id=tenant_id,
        records=[record],
    )
    return _citation_provenance(
        query_run_id=query_run_id,
        tenant_id=tenant_id,
        record=record,
        source_state=source_states.get(record.id),
        claims=_claim_summaries_by_citation(claims).get(citation_id, []),
    )


async def _load_answer_claims(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
) -> list[QueryAnswerClaim]:
    return list(
        await session.scalars(
            select(QueryAnswerClaim)
            .where(
                QueryAnswerClaim.tenant_id == tenant_id,
                QueryAnswerClaim.query_run_id == query_run_id,
            )
            .order_by(QueryAnswerClaim.claim_index)
        )
    )


async def _load_context_records_by_citation(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
) -> dict[str, QueryContextPackRecord]:
    pack = await session.scalar(
        select(QueryContextPack)
        .where(
            QueryContextPack.tenant_id == tenant_id,
            QueryContextPack.query_run_id == query_run_id,
        )
        .order_by(QueryContextPack.pack_version.desc())
        .limit(1)
    )
    if pack is None:
        return {}
    records = list(
        await session.scalars(
            select(QueryContextPackRecord)
            .where(
                QueryContextPackRecord.tenant_id == tenant_id,
                QueryContextPackRecord.query_run_id == query_run_id,
                QueryContextPackRecord.query_context_pack_id == pack.id,
            )
            .order_by(QueryContextPackRecord.citation_id)
        )
    )
    return {record.citation_id: record for record in records}


def _claim_summaries_by_citation(
    claims: list[QueryAnswerClaim],
) -> dict[str, list[QueryCitationClaimProvenance]]:
    summaries: dict[str, list[QueryCitationClaimProvenance]] = {}
    for claim in claims:
        summary = QueryCitationClaimProvenance(
            claim_index=claim.claim_index,
            text=claim.text,
            support_status=claim.support_status,
            support_score=claim.support_score,
            support_reason=claim.support_reason,
            method=claim.method,
        )
        for citation_id in claim.citation_ids:
            summaries.setdefault(citation_id, []).append(summary)
    return summaries


async def _load_context_source_states(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    records: list[QueryContextPackRecord],
) -> dict[UUID, _CitationSourceState]:
    identities = {
        record.id: identity
        for record in records
        if (identity := _citation_source_identity(record)) is not None
    }
    if not identities:
        return {}

    version_ids = {identity[1] for identity in identities.values()}
    rows = (
        await session.execute(
            select(DocumentVersion, Document)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(
                Document.tenant_id == tenant_id,
                DocumentVersion.id.in_(version_ids),
            )
        )
    ).all()
    versions_by_id = {version.id: (version, document) for version, document in rows}

    states: dict[UUID, _CitationSourceState] = {}
    for record_id, (document_id, document_version_id) in identities.items():
        version_and_document = versions_by_id.get(document_version_id)
        if version_and_document is None:
            states[record_id] = _CitationSourceState(
                document_id=document_id,
                document_version_id=document_version_id,
                document_version_status=None,
                active=False,
            )
            continue
        version, document = version_and_document
        states[record_id] = _CitationSourceState(
            document_id=document.id,
            document_version_id=version.id,
            document_version_status=version.status,
            active=(
                document.deleted_at is None
                and version.status == DocumentVersionStatus.ACTIVE
            ),
        )
    return states


def _citation_source_identity(record: QueryContextPackRecord) -> tuple[UUID, UUID] | None:
    document_id = record.metadata_.get("document_id")
    document_version_id = record.metadata_.get("document_version_id")
    if document_id is None or document_version_id is None:
        return None
    try:
        return UUID(str(document_id)), UUID(str(document_version_id))
    except ValueError:
        return None


def _citation_provenance(
    *,
    query_run_id: UUID,
    tenant_id: UUID,
    record: QueryContextPackRecord,
    source_state: _CitationSourceState | None,
    claims: list[QueryCitationClaimProvenance],
) -> QueryCitationProvenance:
    if source_state is None:
        source_state = _CitationSourceState(
            document_id=None,
            document_version_id=None,
            document_version_status=None,
            active=None,
        )
    return QueryCitationProvenance(
        query_run_id=query_run_id,
        tenant_id=tenant_id,
        citation_id=record.citation_id,
        context_id=record.context_id,
        candidate_id=record.candidate_id,
        text=record.text,
        token_count=record.token_count,
        source_ids={key: str(value) for key, value in record.source_ids.items()},
        metadata=dict(record.metadata_),
        source_document_id=source_state.document_id,
        source_document_version_id=source_state.document_version_id,
        source_document_version_status=source_state.document_version_status,
        source_active=source_state.active,
        claims=claims,
    )


def _ordered_unique(values: Any) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
