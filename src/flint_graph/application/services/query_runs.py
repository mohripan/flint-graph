from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.query_orchestration import (
    AnswerFaithfulnessReport,
    QueryCandidate,
    QueryEntityLink,
)
from flint_graph.application.query_orchestration import (
    QueryContextPack as ApplicationQueryContextPack,
)
from flint_graph.domain.enums import (
    QueryRunStatus,
    RetrievalIndexScope,
    RetrievalIndexVersionStatus,
)
from flint_graph.domain.errors import ConflictError, NotFoundError
from flint_graph.domain.transitions import can_transition_query_run
from flint_graph.infrastructure.db.models import (
    QueryAnswerClaim,
    QueryContextPack,
    QueryContextPackRecord,
    QueryRun,
    QueryRunCandidate,
    QueryRunEvent,
    QueryRunLinkedEntity,
    RetrievalIndexVersion,
)

_TERMINAL_STATUSES = {
    QueryRunStatus.COMPLETED,
    QueryRunStatus.FAILED,
    QueryRunStatus.CANCELLED,
}
_MAX_JSON_BYTES = 8192


@dataclass(frozen=True, slots=True)
class QueryRunCreate:
    tenant_id: UUID
    query_text: str
    retrieval_index_version_id: UUID
    metadata: dict[str, Any] = field(default_factory=dict)


async def create_query_run(
    session: AsyncSession,
    spec: QueryRunCreate,
) -> QueryRun:
    query_text = _normalize_query_text(spec.query_text)
    if not query_text:
        raise ConflictError("query_text is required.")
    _validate_json_size("metadata", spec.metadata)
    await _require_visible_active_index_version(
        session,
        tenant_id=spec.tenant_id,
        retrieval_index_version_id=spec.retrieval_index_version_id,
    )

    run = QueryRun(
        tenant_id=spec.tenant_id,
        retrieval_index_version_id=spec.retrieval_index_version_id,
        query_text=query_text,
        normalized_query_hash=_query_hash(query_text),
        status=QueryRunStatus.QUEUED,
        classification_metadata={},
        answer_citations=[],
        candidate_count=0,
        context_token_count=0,
        error_details={},
        metadata_=dict(spec.metadata),
    )
    session.add(run)
    await session.flush()
    return run


async def get_query_run(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
) -> QueryRun:
    run = await session.scalar(
        select(QueryRun).where(QueryRun.id == query_run_id, QueryRun.tenant_id == tenant_id)
    )
    if run is None:
        raise NotFoundError(f"Query run '{query_run_id}' was not found.")
    return run


async def list_query_runs(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    limit: int = 50,
    before_id: UUID | None = None,
    query: str | None = None,
) -> list[QueryRun]:
    statement = select(QueryRun).where(QueryRun.tenant_id == tenant_id)
    if before_id is not None:
        cursor = await get_query_run(session, tenant_id=tenant_id, query_run_id=before_id)
        statement = statement.where(or_(
            QueryRun.created_at < cursor.created_at,
            and_(QueryRun.created_at == cursor.created_at, QueryRun.id < cursor.id),
        ))
    if query and query.strip():
        # Literal substring search; '%' and '_' supplied by users are not wildcards.
        statement = statement.where(QueryRun.query_text.icontains(query.strip(), autoescape=True))
    return list(
        await session.scalars(
            statement
            .order_by(QueryRun.created_at.desc(), QueryRun.id.desc())
            .limit(limit)
        )
    )


async def transition_query_run(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
    target_status: QueryRunStatus,
    event_type: str,
    payload: dict[str, Any],
    answer_text: str | None = None,
    answer_citations: list[dict[str, Any]] | None = None,
    abstained: bool | None = None,
    abstain_reason: str | None = None,
    supported_claim_count: int | None = None,
    unsupported_claim_count: int | None = None,
    support_method: str | None = None,
    answer_provider: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    error_details: dict[str, Any] | None = None,
) -> QueryRun:
    run = await _load_query_run_for_update(
        session,
        tenant_id=tenant_id,
        query_run_id=query_run_id,
    )
    if run.status == target_status:
        return run
    if not can_transition_query_run(run.status, target_status):
        raise ConflictError(
            f"Cannot transition query run '{query_run_id}' from "
            f"'{run.status}' to '{target_status}'."
        )

    now = datetime.now(UTC)
    run.status = target_status
    if target_status == QueryRunStatus.RUNNING and run.started_at is None:
        run.started_at = now
    if target_status in _TERMINAL_STATUSES and run.completed_at is None:
        run.completed_at = now
    if target_status == QueryRunStatus.FAILED:
        run.failed_at = now
        run.error_code = error_code
        run.error_message = error_message
        run.error_details = dict(error_details or {})
    if target_status == QueryRunStatus.CANCELLED:
        run.cancelled_at = now
    if target_status == QueryRunStatus.COMPLETED:
        run.answer_text = answer_text
        run.answer_citations = list(answer_citations or [])
        if abstained is not None:
            run.abstained = abstained
        run.abstain_reason = abstain_reason
        if supported_claim_count is not None:
            run.supported_claim_count = supported_claim_count
        if unsupported_claim_count is not None:
            run.unsupported_claim_count = unsupported_claim_count
        run.support_method = support_method
        run.answer_provider = answer_provider
        run.error_code = None
        run.error_message = None
        run.error_details = {}

    await _append_event_for_locked_run(
        session,
        run=run,
        event_type=event_type,
        payload=payload,
        created_at=now,
    )
    await session.flush()
    return run


async def append_query_run_event(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
    event_type: str,
    payload: dict[str, Any],
) -> QueryRunEvent:
    run = await _load_query_run_for_update(
        session,
        tenant_id=tenant_id,
        query_run_id=query_run_id,
    )
    event = await _append_event_for_locked_run(
        session,
        run=run,
        event_type=event_type,
        payload=payload,
        created_at=datetime.now(UTC),
    )
    await session.flush()
    return event


async def list_query_run_events(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
) -> list[QueryRunEvent]:
    await get_query_run(session, tenant_id=tenant_id, query_run_id=query_run_id)
    return list(
        await session.scalars(
            select(QueryRunEvent)
            .where(
                QueryRunEvent.tenant_id == tenant_id,
                QueryRunEvent.query_run_id == query_run_id,
            )
            .order_by(QueryRunEvent.sequence)
        )
    )


async def persist_query_diagnostics(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
) -> dict[str, Any]:
    run = await _load_query_run_for_update(
        session,
        tenant_id=tenant_id,
        query_run_id=query_run_id,
    )
    events = list(
        await session.scalars(
            select(QueryRunEvent)
            .where(
                QueryRunEvent.tenant_id == tenant_id,
                QueryRunEvent.query_run_id == query_run_id,
            )
            .order_by(QueryRunEvent.sequence)
        )
    )
    diagnostics = _build_query_diagnostics(run, events)
    run.metadata_ = {**run.metadata_, "diagnostics": diagnostics}
    await session.flush()
    return diagnostics


async def record_query_classification(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
    label: str,
    strategy: str,
    confidence: float,
    metadata: dict[str, Any],
) -> QueryRun:
    if not 0.0 <= confidence <= 1.0:
        raise ConflictError("classification confidence must be between 0 and 1.")
    _validate_json_size("classification metadata", metadata)
    run = await _load_query_run_for_update(
        session,
        tenant_id=tenant_id,
        query_run_id=query_run_id,
    )
    run.classification_label = label
    run.retrieval_strategy = strategy
    run.classification_confidence = confidence
    run.classification_metadata = dict(metadata)
    await session.flush()
    return run


async def persist_query_entity_link(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
    link: QueryEntityLink,
) -> QueryRunLinkedEntity:
    await get_query_run(session, tenant_id=tenant_id, query_run_id=query_run_id)
    row = QueryRunLinkedEntity(
        tenant_id=tenant_id,
        query_run_id=query_run_id,
        canonical_entity_id=link.canonical_entity_id,
        mention_text=link.mention_text,
        status=link.status,
        score=link.score,
        method=link.method,
        candidate_entity_ids=[str(entity_id) for entity_id in link.candidate_entity_ids],
        reasons=list(link.reasons),
        metadata_={},
    )
    session.add(row)
    await session.flush()
    return row


async def persist_query_answer_claims(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
    report: AnswerFaithfulnessReport,
) -> list[QueryAnswerClaim]:
    await get_query_run(session, tenant_id=tenant_id, query_run_id=query_run_id)
    await session.execute(
        delete(QueryAnswerClaim).where(
            QueryAnswerClaim.tenant_id == tenant_id,
            QueryAnswerClaim.query_run_id == query_run_id,
        )
    )
    rows: list[QueryAnswerClaim] = []
    for claim in sorted(report.claims, key=lambda item: item.claim_index):
        row = QueryAnswerClaim(
            tenant_id=tenant_id,
            query_run_id=query_run_id,
            claim_index=claim.claim_index,
            text=claim.text,
            citation_ids=list(claim.citation_ids),
            support_status=claim.support_status,
            support_score=claim.support_score,
            support_reason=claim.support_reason,
            method=claim.method,
        )
        session.add(row)
        rows.append(row)
    await session.flush()
    return rows


async def persist_query_candidate(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
    candidate: QueryCandidate,
) -> QueryRunCandidate:
    if candidate.tenant_id != tenant_id:
        raise ConflictError("candidate tenant_id must match query run tenant_id.")
    _validate_json_size("candidate metadata", candidate.metadata)
    run = await _load_query_run_for_update(
        session,
        tenant_id=tenant_id,
        query_run_id=query_run_id,
    )
    row = QueryRunCandidate(
        tenant_id=tenant_id,
        query_run_id=query_run_id,
        retrieval_index_version_id=candidate.retrieval_index_version_id,
        source=candidate.source,
        candidate_type=candidate.candidate_type,
        source_ids=dict(candidate.source_ids),
        dedupe_key=candidate.candidate_id,
        text_preview=candidate.text_preview,
        raw_score=candidate.raw_score,
        normalized_score=candidate.normalized_score,
        rank=candidate.rank,
        fusion_score=candidate.fusion_score,
        rerank_score=candidate.rerank_score,
        rerank_rank=candidate.rerank_rank,
        reasons=list(candidate.reasons),
        metadata_=dict(candidate.metadata),
    )
    run.candidate_count += 1
    session.add(row)
    await session.flush()
    return row


async def persist_query_context_pack(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
    context_pack: ApplicationQueryContextPack,
) -> QueryContextPack:
    _validate_json_size("context pack metadata", context_pack.metadata)
    run = await _load_query_run_for_update(
        session,
        tenant_id=tenant_id,
        query_run_id=query_run_id,
    )
    selected_candidate_ids = [record.candidate_id for record in context_pack.records]
    citation_map = {
        record.citation_id: {
            "context_id": record.context_id,
            "candidate_id": record.candidate_id,
            "source_ids": record.source_ids,
        }
        for record in context_pack.records
    }
    token_count = sum(record.token_count for record in context_pack.records)
    pack = QueryContextPack(
        tenant_id=tenant_id,
        query_run_id=query_run_id,
        pack_id=context_pack.pack_id,
        pack_version=context_pack.pack_version,
        token_budget=context_pack.token_budget,
        token_count=token_count,
        selected_candidate_ids=selected_candidate_ids,
        citation_map=citation_map,
        metadata_=dict(context_pack.metadata),
    )
    session.add(pack)
    await session.flush()

    for record in context_pack.records:
        session.add(
            QueryContextPackRecord(
                query_context_pack_id=pack.id,
                tenant_id=tenant_id,
                query_run_id=query_run_id,
                context_id=record.context_id,
                candidate_id=record.candidate_id,
                citation_id=record.citation_id,
                text=record.text,
                token_count=record.token_count,
                source_ids=dict(record.source_ids),
                metadata_=dict(record.metadata),
            )
        )

    run.context_token_count = token_count
    await session.flush()
    return pack


async def _load_query_run_for_update(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
) -> QueryRun:
    run = await session.scalar(
        select(QueryRun)
        .where(QueryRun.id == query_run_id, QueryRun.tenant_id == tenant_id)
        .with_for_update()
    )
    if run is None:
        raise NotFoundError(f"Query run '{query_run_id}' was not found.")
    return run


async def _append_event_for_locked_run(
    session: AsyncSession,
    *,
    run: QueryRun,
    event_type: str,
    payload: dict[str, Any],
    created_at: datetime,
) -> QueryRunEvent:
    if not event_type:
        raise ConflictError("event_type is required.")
    _validate_json_size("event payload", payload)
    max_sequence = await session.scalar(
        select(func.max(QueryRunEvent.sequence)).where(QueryRunEvent.query_run_id == run.id)
    )
    event = QueryRunEvent(
        tenant_id=run.tenant_id,
        query_run_id=run.id,
        sequence=(max_sequence or 0) + 1,
        event_type=event_type,
        payload=dict(payload),
        created_at=created_at,
    )
    session.add(event)
    return event


async def _require_visible_active_index_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    retrieval_index_version_id: UUID,
) -> RetrievalIndexVersion:
    version = await session.scalar(
        select(RetrievalIndexVersion).where(
            RetrievalIndexVersion.id == retrieval_index_version_id,
            RetrievalIndexVersion.status == RetrievalIndexVersionStatus.ACTIVE,
            (
                (
                    RetrievalIndexVersion.scope == RetrievalIndexScope.GLOBAL
                )
                & RetrievalIndexVersion.tenant_id.is_(None)
            )
            | (
                (RetrievalIndexVersion.scope == RetrievalIndexScope.TENANT)
                & (RetrievalIndexVersion.tenant_id == tenant_id)
            ),
        )
    )
    if version is None:
        raise NotFoundError(
            f"Retrieval index version '{retrieval_index_version_id}' was not found."
        )
    return version


def _normalize_query_text(query_text: str) -> str:
    return " ".join(query_text.split())


def _query_hash(query_text: str) -> str:
    normalized = query_text.casefold()
    digest = sha256(normalized.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _validate_json_size(name: str, value: Any) -> None:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    if len(encoded) > _MAX_JSON_BYTES:
        raise ConflictError(f"{name} exceeds {_MAX_JSON_BYTES} bytes.")


def _build_query_diagnostics(
    run: QueryRun,
    events: list[QueryRunEvent],
) -> dict[str, Any]:
    retriever_candidate_counts: dict[str, int] = {}
    failed_retrievers: list[str] = []
    retrieved_candidate_count = 0
    fused_candidate_count = 0
    reranked_candidate_count = 0
    context_record_count = 0
    context_token_count = run.context_token_count
    skipped_context_count = 0
    answer_provider = run.answer_provider

    for event in events:
        payload = event.payload
        if event.event_type == "retrieval.progress":
            source = payload.get("source")
            if isinstance(source, str) and payload.get("status") == "completed":
                retriever_candidate_counts[source] = int(payload.get("candidate_count") or 0)
            if isinstance(source, str) and payload.get("status") == "failed":
                failed_retrievers.append(source)
        elif event.event_type == "retrieval.completed":
            retrieved_candidate_count = int(payload.get("candidate_count") or 0)
            raw_failed = payload.get("failed_retrievers")
            if isinstance(raw_failed, list):
                failed_retrievers = [item for item in raw_failed if isinstance(item, str)]
        elif event.event_type == "fusion.completed":
            fused_candidate_count = int(payload.get("fused_candidate_count") or 0)
        elif event.event_type == "rerank.completed":
            reranked_candidate_count = int(payload.get("candidate_count") or 0)
        elif event.event_type == "context.packed":
            context_record_count = int(payload.get("record_count") or 0)
            context_token_count = int(payload.get("token_count") or 0)
            skipped_context_count = int(payload.get("skipped_candidate_count") or 0)
        elif event.event_type == "answer.finalized":
            provider = payload.get("answer_provider")
            if isinstance(provider, str) and provider:
                answer_provider = provider

    support_status_counts: dict[str, int] = {}
    if run.supported_claim_count:
        support_status_counts["supported"] = run.supported_claim_count
    if run.unsupported_claim_count:
        support_status_counts["unsupported"] = run.unsupported_claim_count

    return {
        "retriever_candidate_counts": retriever_candidate_counts,
        "failed_retrievers": failed_retrievers,
        "retrieved_candidate_count": retrieved_candidate_count,
        "fused_candidate_count": fused_candidate_count,
        "reranked_candidate_count": reranked_candidate_count,
        "context_record_count": context_record_count,
        "context_token_count": context_token_count,
        "skipped_context_count": skipped_context_count,
        "citation_repair_counts": {},
        "support_status_counts": support_status_counts,
        "abstention_reason": run.abstain_reason,
        "answer_provider": answer_provider,
        "support_provider": run.support_method,
        "model_metadata": {},
    }
