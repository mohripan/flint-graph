"""Bounded question scope from revalidated finalized conversation state."""

import json
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.conversation_memory import (
    MEMORY_POLICY_VERSION,
    FollowupInterpretation,
    interpret_followup,
)
from flint_graph.application.grounded_prompt_rules import (
    ANSWER_PROMPT_VERSION,
    SUPPORT_PROMPT_VERSION,
)
from flint_graph.application.services.query_runs import get_query_run
from flint_graph.application.services.retrieval import require_visible_index_version
from flint_graph.config import Settings
from flint_graph.domain.enums import (
    DocumentIndexCoverageStatus,
    DocumentVersionStatus,
    QueryRunStatus,
)
from flint_graph.domain.errors import NotFoundError
from flint_graph.infrastructure.answer_generator_factory import (
    answer_generator_model,
    support_checker_model,
)
from flint_graph.infrastructure.db.models import (
    ConversationTurn,
    Document,
    DocumentChunk,
    DocumentIndexCoverage,
    DocumentVersion,
    QueryAnswerClaim,
    QueryContextPack,
    QueryContextPackRecord,
    QueryRun,
)


def conversation_policy_fingerprint(settings: Settings) -> str:
    policy = {
        "version": MEMORY_POLICY_VERSION,
        "answer": [settings.query_answer_provider, answer_generator_model(settings)],
        "support": [settings.query_support_provider, support_checker_model(settings)],
        "answer_prompt": ANSWER_PROMPT_VERSION,
        "support_prompt": SUPPORT_PROMPT_VERSION,
        "context": settings.query_context_token_budget,
        "records": settings.query_max_context_records,
        "output": settings.query_answer_max_tokens,
        "ollama_context": settings.query_ollama_context_tokens,
        "temperature": settings.query_answer_temperature,
        "support_ratio": settings.query_min_supported_claim_ratio,
        "context_relevance": settings.query_min_context_relevance,
        "anthropic_support_output": settings.anthropic_support_max_tokens,
        "anthropic_effort": settings.anthropic_effort,
        "graph_depth": settings.query_graph_depth,
        "candidate_limit": settings.query_max_candidate_limit,
    }
    return sha256(json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def effective_query_text(run: QueryRun) -> str:
    context = run.metadata_.get("conversation_context", {})
    if (
        isinstance(context, dict)
        and context.get("policy_version") == MEMORY_POLICY_VERSION
        and context.get("mode") == "resolved"
    ):
        resolved = context.get("resolved_query")
        if isinstance(resolved, str) and 0 < len(resolved) <= 1000:
            return resolved
    return run.query_text


async def prepare_conversation_context(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
    policy_fingerprint: str | None,
) -> FollowupInterpretation:
    run = await get_query_run(session, tenant_id=tenant_id, query_run_id=query_run_id)
    turn = await session.scalar(
        select(ConversationTurn).where(
            ConversationTurn.tenant_id == tenant_id,
            ConversationTurn.query_run_id == query_run_id,
        )
    )
    if turn is None:
        return FollowupInterpretation("independent", run.query_text, "standalone_query")
    result = interpret_followup(run.query_text, None)
    previous = None
    reason = result.reason
    if result.mode == "clarification":
        previous = await session.scalar(
            select(ConversationTurn).where(
                ConversationTurn.tenant_id == tenant_id,
                ConversationTurn.conversation_id == turn.conversation_id,
                ConversationTurn.turn_number == turn.turn_number - 1,
            )
        )
        if previous is not None:
            prior_run = await get_query_run(
                session, tenant_id=tenant_id, query_run_id=previous.query_run_id
            )
            await session.refresh(prior_run)
            if await _trusted_previous_run(
                session, run=prior_run, current=run, fingerprint=policy_fingerprint
            ):
                result = interpret_followup(run.query_text, effective_query_text(prior_run))
                reason = result.reason
            else:
                reason = "previous_turn_untrusted_or_stale"
    run.metadata_ = {
        **run.metadata_,
        "conversation": {**run.metadata_.get("conversation", {}), "memory_mode": result.mode},
        "conversation_context": {
            "policy_version": MEMORY_POLICY_VERSION,
            "execution_policy_fingerprint": policy_fingerprint,
            "mode": result.mode,
            "reason": reason,
            "resolved_query": result.query if result.mode == "resolved" else None,
            "previous_turn_id": str(previous.id) if previous is not None else None,
            "previous_run_id": str(previous.query_run_id) if previous is not None else None,
            "considered_turn_count": 1 if previous is not None else 0,
            "omitted_turn_count": max(turn.turn_number - 1 - (1 if previous is not None else 0), 0),
        },
    }
    await session.flush()
    return FollowupInterpretation(result.mode, result.query, reason)


async def _trusted_previous_run(
    session: AsyncSession,
    *,
    run: QueryRun,
    current: QueryRun,
    fingerprint: str | None,
) -> bool:
    context = run.metadata_.get("conversation_context", {})
    if (
        not isinstance(context, dict)
        or context.get("policy_version") != MEMORY_POLICY_VERSION
        or context.get("mode") not in {"independent", "resolved"}
        or fingerprint is None
        or context.get("execution_policy_fingerprint") != fingerprint
        or run.status != QueryRunStatus.COMPLETED
        or run.abstained
        or not 1 <= run.supported_claim_count <= 8
        or run.unsupported_claim_count != 0
        or run.retrieval_index_version_id != current.retrieval_index_version_id
        or run.metadata_.get("filters", {}) != current.metadata_.get("filters", {})
        or not 1 <= len(run.answer_citations) <= 8
    ):
        return False
    try:
        await require_visible_index_version(
            session,
            tenant_id=run.tenant_id,
            retrieval_index_version_id=current.retrieval_index_version_id,
            require_active=True,
        )
    except NotFoundError:
        return False
    claims = list(
        await session.scalars(
            select(QueryAnswerClaim)
            .where(
                QueryAnswerClaim.tenant_id == run.tenant_id,
                QueryAnswerClaim.query_run_id == run.id,
            )
            .limit(9)
            .execution_options(populate_existing=True)
        )
    )
    if len(claims) != run.supported_claim_count or any(
        claim.support_status != "supported" or not claim.citation_ids for claim in claims
    ):
        return False
    citation_ids = {citation.get("citation_id") for citation in run.answer_citations}
    if (
        None in citation_ids
        or len(citation_ids) != len(run.answer_citations)
        or {citation for claim in claims for citation in claim.citation_ids} != citation_ids
    ):
        return False
    for citation in run.answer_citations:
        record = await session.scalar(
            select(QueryContextPackRecord)
            .execution_options(populate_existing=True)
            .where(
                QueryContextPackRecord.tenant_id == run.tenant_id,
                QueryContextPackRecord.query_run_id == run.id,
                QueryContextPackRecord.citation_id == citation["citation_id"],
                QueryContextPackRecord.context_id == citation.get("context_id"),
                QueryContextPackRecord.query_context_pack_id
                == (
                    select(QueryContextPack.id)
                    .where(
                        QueryContextPack.tenant_id == run.tenant_id,
                        QueryContextPack.query_run_id == run.id,
                    )
                    .order_by(QueryContextPack.pack_version.desc())
                    .limit(1)
                    .scalar_subquery()
                ),
            )
        )
        if record is None or record.metadata_.get("evidence_origin") != "postgresql_chunk":
            return False
        if citation.get("source_ids") != record.source_ids:
            return False
        try:
            document_id = UUID(record.source_ids["document_id"])
            version_id = UUID(record.source_ids["document_version_id"])
            chunk_id = record.source_ids["chunk_id"]
        except (KeyError, TypeError, ValueError):
            return False
        chunk = await session.scalar(
            select(DocumentChunk)
            .execution_options(populate_existing=True)
            .join(
                DocumentVersion,
                DocumentVersion.id == DocumentChunk.document_version_id,
            )
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(
                DocumentIndexCoverage,
                (DocumentIndexCoverage.document_version_id == DocumentVersion.id)
                & (DocumentIndexCoverage.document_id == Document.id)
                & (DocumentIndexCoverage.tenant_id == run.tenant_id),
            )
            .where(
                DocumentChunk.tenant_id == run.tenant_id,
                Document.tenant_id == run.tenant_id,
                DocumentChunk.document_id == document_id,
                DocumentVersion.document_id == document_id,
                DocumentChunk.document_version_id == version_id,
                DocumentChunk.chunk_id == chunk_id,
                Document.deleted_at.is_(None),
                DocumentVersion.status == DocumentVersionStatus.ACTIVE,
                DocumentIndexCoverage.retrieval_index_version_id
                == current.retrieval_index_version_id,
                DocumentIndexCoverage.status == DocumentIndexCoverageStatus.COMPLETED,
            )
        )
        if (
            chunk is None
            or record.text != chunk.text
            or record.metadata_.get("chunk_hash") != chunk.chunk_hash
            or chunk.chunk_hash != "sha256:" + sha256(chunk.text.encode()).hexdigest()
        ):
            return False
    return True
