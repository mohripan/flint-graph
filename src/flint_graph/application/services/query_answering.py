from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.query_orchestration import (
    AnswerGenerationRequest,
    AnswerGenerator,
    DeterministicAnswerGenerator,
    PackedContextRecord,
    StreamingAnswerGenerator,
    SupportChecker,
)
from flint_graph.application.query_orchestration import (
    QueryContextPack as ApplicationQueryContextPack,
)
from flint_graph.application.services.query_faithfulness import (
    QueryFaithfulnessPolicy,
    faithfulness_summary,
    verify_generated_answer,
)
from flint_graph.application.services.query_runs import (
    append_query_run_event,
    get_query_run,
    persist_query_answer_claims,
    transition_query_run,
)
from flint_graph.application.services.usage import record_provider_usage
from flint_graph.application.usage import usage_from_metadata
from flint_graph.domain.enums import ProviderUsageOperation, QueryRunStatus
from flint_graph.infrastructure.db.models import (
    QueryContextPack,
    QueryContextPackRecord,
)
from flint_graph.observability import metrics
from flint_graph.observability.instruments import QUERY_ABSTENTIONS, QUERY_CLAIMS


@dataclass(frozen=True, slots=True)
class QueryAnswerResult:
    status: QueryRunStatus
    answer_text: str | None = None
    answer_citation_count: int = 0
    insufficient_context: bool = False
    errors: list[dict[str, Any]] = field(default_factory=list)


async def generate_query_answer(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
    generator: AnswerGenerator | None = None,
    support_checker: SupportChecker | None = None,
    min_supported_claim_ratio: float = 0.5,
    min_context_relevance: float = 0.0,
    usage_pricing: dict[str, dict[str, float]] | None = None,
    usage_currency: str = "USD",
) -> QueryAnswerResult:
    run = await get_query_run(session, tenant_id=tenant_id, query_run_id=query_run_id)
    stage = "load_context"
    try:
        context_pack = await _load_latest_context_pack(
            session,
            tenant_id=tenant_id,
            query_run_id=query_run_id,
        )
        model = generator or DeterministicAnswerGenerator()
        generation_request = AnswerGenerationRequest(
            tenant_id=tenant_id,
            query=run.query_text,
            retrieval_index_version_id=run.retrieval_index_version_id,
            context_pack=context_pack,
        )
        stage = "generate_answer"
        if isinstance(model, StreamingAnswerGenerator):
            draft_answer = await model.stream_generate(
                generation_request,
                _provisional_delta_recorder(
                    session=session,
                    tenant_id=tenant_id,
                    query_run_id=query_run_id,
                ),
            )
        else:
            draft_answer = await model.generate(generation_request)
        stage = "support_check"
        verification = await verify_generated_answer(
            tenant_id=tenant_id,
            query=run.query_text,
            context_pack=context_pack,
            draft_answer=draft_answer,
            support_checker=support_checker,
            policy=QueryFaithfulnessPolicy(
                min_supported_claim_ratio=min_supported_claim_ratio,
                min_context_relevance=min_context_relevance,
            ),
        )
        stage = "persist_answer"
        answer = verification.answer
        faithfulness = faithfulness_summary(verification.report)
        answer_provider = _answer_provider(draft_answer)
        await _record_answer_usage(
            session,
            tenant_id=tenant_id,
            query_run_id=query_run_id,
            draft_answer=draft_answer,
            support_metadata=verification.report.metadata.get("support"),
            pricing=usage_pricing or {},
            currency=usage_currency,
        )
        _record_answer_metrics(verification.report)
        answer_citations = [citation.model_dump(mode="json") for citation in answer.citations]
        await persist_query_answer_claims(
            session,
            tenant_id=tenant_id,
            query_run_id=query_run_id,
            report=verification.report,
        )
        await append_query_run_event(
            session,
            tenant_id=tenant_id,
            query_run_id=query_run_id,
            event_type="answer.delta",
            payload={
                "text": answer.text,
                "char_count": len(answer.text),
                "insufficient_context": answer.insufficient_context,
                "provisional": False,
                "faithfulness": faithfulness,
            },
        )
        for citation in answer_citations:
            await append_query_run_event(
                session,
                tenant_id=tenant_id,
                query_run_id=query_run_id,
                event_type="answer.citation",
                payload=citation,
            )
        await append_query_run_event(
            session,
            tenant_id=tenant_id,
            query_run_id=query_run_id,
            event_type="support.checked",
            payload={
                "supported_claim_count": verification.report.supported_claim_count,
                "unsupported_claim_count": verification.report.unsupported_claim_count,
                "support_method": verification.report.support_method,
                "abstained": verification.report.abstained,
            },
        )
        if verification.report.abstained:
            await append_query_run_event(
                session,
                tenant_id=tenant_id,
                query_run_id=query_run_id,
                event_type="answer.abstained",
                payload={
                    "reason": verification.report.abstain_reason,
                    "supported_claim_count": verification.report.supported_claim_count,
                    "unsupported_claim_count": verification.report.unsupported_claim_count,
                },
            )
        await append_query_run_event(
            session,
            tenant_id=tenant_id,
            query_run_id=query_run_id,
            event_type="answer.finalized",
            payload={
                "answer_text": answer.text,
                "answer_citations": answer_citations,
                "answer_char_count": len(answer.text),
                "answer_citation_count": len(answer.citations),
                "insufficient_context": answer.insufficient_context,
                "faithfulness": faithfulness,
                "answer_provider": answer_provider,
            },
        )
        await transition_query_run(
            session,
            tenant_id=tenant_id,
            query_run_id=query_run_id,
            target_status=QueryRunStatus.COMPLETED,
            event_type="query.completed",
            payload={
                "answer_char_count": len(answer.text),
                "answer_citation_count": len(answer.citations),
                "insufficient_context": answer.insufficient_context,
                "faithfulness": faithfulness,
            },
            answer_text=answer.text,
            answer_citations=answer_citations,
            abstained=verification.report.abstained,
            abstain_reason=verification.report.abstain_reason,
            supported_claim_count=verification.report.supported_claim_count,
            unsupported_claim_count=verification.report.unsupported_claim_count,
            support_method=verification.report.support_method,
            answer_provider=answer_provider,
        )
        return QueryAnswerResult(
            status=QueryRunStatus.COMPLETED,
            answer_text=answer.text,
            answer_citation_count=len(answer.citations),
            insufficient_context=answer.insufficient_context,
        )
    except Exception as exc:
        code, message = {
            "load_context": ("answer_context_failed", "Answer context could not be loaded."),
            "generate_answer": (
                "answer_generation_failed",
                "The answer provider could not generate an answer.",
            ),
            "support_check": (
                "support_check_failed",
                "The support checker could not verify the answer.",
            ),
            "persist_answer": (
                "answer_persistence_failed",
                "The verified answer could not be saved.",
            ),
        }[stage]
        error = {
            "stage": stage,
            "error_code": code,
            "error_message": message,
            "error_type": type(exc).__name__,
        }
        await transition_query_run(
            session,
            tenant_id=tenant_id,
            query_run_id=query_run_id,
            target_status=QueryRunStatus.FAILED,
            event_type="query.failed",
            payload={"stage": stage, "errors": [error]},
            error_code=code,
            error_message=message,
            error_details={"errors": [error]},
        )
        return QueryAnswerResult(status=QueryRunStatus.FAILED, errors=[error])


async def _record_answer_usage(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
    draft_answer: object,
    support_metadata: object,
    pricing: dict[str, dict[str, float]],
    currency: str,
) -> None:
    """Persist what generation and support checking consumed.

    Two rows, not one: generation and the support check can run on different
    providers and models, and collapsing them would make per-model cost
    attribution impossible.
    """
    answer_metadata = getattr(draft_answer, "metadata", None)
    await record_provider_usage(
        session,
        tenant_id=tenant_id,
        usage=usage_from_metadata(
            answer_metadata if isinstance(answer_metadata, dict) else None,
            operation=ProviderUsageOperation.ANSWER,
        ),
        pricing=pricing,
        currency=currency,
        query_run_id=query_run_id,
    )
    if isinstance(support_metadata, dict) and support_metadata:
        await record_provider_usage(
            session,
            tenant_id=tenant_id,
            usage=usage_from_metadata(
                support_metadata,
                operation=ProviderUsageOperation.FAITHFULNESS,
            ),
            pricing=pricing,
            currency=currency,
            query_run_id=query_run_id,
        )


def _record_answer_metrics(report: object) -> None:
    supported = getattr(report, "supported_claim_count", 0)
    unsupported = getattr(report, "unsupported_claim_count", 0)
    if supported:
        metrics.add(QUERY_CLAIMS, supported, **{"flint_graph.support.status": "supported"})
    if unsupported:
        metrics.add(QUERY_CLAIMS, unsupported, **{"flint_graph.support.status": "unsupported"})
    if getattr(report, "abstained", False):
        reason = getattr(report, "abstain_reason", None) or "unspecified"
        metrics.add(QUERY_ABSTENTIONS, **{"flint_graph.abstain.reason": reason})


def _answer_provider(answer: object) -> str:
    metadata = getattr(answer, "metadata", {})
    if isinstance(metadata, dict):
        provider = metadata.get("provider")
        if isinstance(provider, str) and provider:
            return provider
    return "unknown"


def _provisional_delta_recorder(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    query_run_id: UUID,
) -> Callable[[str], Awaitable[None]]:
    async def record_delta(text: str) -> None:
        if not text:
            return
        await append_query_run_event(
            session,
            tenant_id=tenant_id,
            query_run_id=query_run_id,
            event_type="answer.delta",
            payload={
                "text": text,
                "char_count": len(text),
                "insufficient_context": False,
                "provisional": True,
            },
        )

    return record_delta


async def _load_latest_context_pack(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
) -> ApplicationQueryContextPack:
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
        return ApplicationQueryContextPack(
            pack_id=f"query-pack-{query_run_id}",
            token_budget=1,
            records=[],
            metadata={"source": "missing-context-pack"},
        )

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
    return ApplicationQueryContextPack(
        pack_id=pack.pack_id,
        pack_version=pack.pack_version,
        token_budget=pack.token_budget,
        records=[
            PackedContextRecord(
                context_id=record.context_id,
                candidate_id=record.candidate_id,
                citation_id=record.citation_id,
                text=record.text,
                token_count=record.token_count,
                source_ids=dict(record.source_ids),
                metadata=dict(record.metadata_),
            )
            for record in records
        ],
        metadata=dict(pack.metadata_),
    )
