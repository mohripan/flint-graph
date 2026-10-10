from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.conversation_memory import MEMORY_POLICY_VERSION
from flint_graph.application.financial_arithmetic import prepare_verified_calculation
from flint_graph.application.query_orchestration import (
    AnswerFaithfulnessReport,
    AnswerGenerationRequest,
    AnswerGenerator,
    DeterministicAnswerGenerator,
    GeneratedAnswer,
    PackedContextRecord,
    StreamingAnswerGenerator,
    SupportChecker,
)
from flint_graph.application.query_orchestration import (
    QueryContextPack as ApplicationQueryContextPack,
)
from flint_graph.application.services.conversation_memory import (
    effective_query_text,
    prepare_conversation_context,
)
from flint_graph.application.services.query_faithfulness import (
    QueryFaithfulnessPolicy,
    QueryFaithfulnessResult,
    faithfulness_summary,
    verify_generated_answer,
)
from flint_graph.application.services.query_runs import (
    append_query_run_event,
    get_query_run,
    persist_query_answer_claims,
    transition_query_run,
)
from flint_graph.application.services.query_scope import (
    FinancialScopeClarification,
    financial_scope_clarification,
)
from flint_graph.application.services.query_usage import QueryUsageRecorder
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
    usage_recorder: QueryUsageRecorder | None = None,
    conversation_fingerprint: str | None = None,
) -> QueryAnswerResult:
    run = await get_query_run(session, tenant_id=tenant_id, query_run_id=query_run_id)
    stage = "load_context"
    try:
        if run.metadata_.get("conversation_context", {}).get("mode") == "resolved":
            await prepare_conversation_context(
                session,
                tenant_id=tenant_id,
                query_run_id=query_run_id,
                policy_fingerprint=conversation_fingerprint,
            )
        query = effective_query_text(run)
        context_pack = await _load_latest_context_pack(
            session,
            tenant_id=tenant_id,
            query_run_id=query_run_id,
        )
        filters = run.metadata_.get("filters", {})
        clarification = await financial_scope_clarification(
            session,
            tenant_id=tenant_id,
            query=query,
            retrieval_index_version_id=run.retrieval_index_version_id,
            filters=filters if isinstance(filters, dict) else {},
        )
        clarification_reason = "ambiguous_financial_scope"
        clarification_version = "financial-scope-v1"
        if run.metadata_.get("conversation_context", {}).get("mode") == "clarification":
            clarification = FinancialScopeClarification(
                text="Please ask a self-contained question, including the subject and year. "
                "I cannot safely resolve this follow-up from the preceding turn.",
                missing_scope=["conversation_scope"],
            )
            clarification_reason = "ambiguous_conversation_scope"
            clarification_version = MEMORY_POLICY_VERSION
        model = generator or DeterministicAnswerGenerator()
        calculation_hint = prepare_verified_calculation(query, context_pack)
        generation_request = AnswerGenerationRequest(
            tenant_id=tenant_id,
            query=query,
            retrieval_index_version_id=run.retrieval_index_version_id,
            context_pack=context_pack,
            policy={"verified_calculation": calculation_hint}
            if calculation_hint is not None
            else {},
        )
        if calculation_hint is not None:
            run.metadata_ = {**run.metadata_, "arithmetic_preparation": calculation_hint}
            await session.flush()
        stage = "generate_answer"

        async def generate_draft() -> GeneratedAnswer:
            try:
                if isinstance(model, StreamingAnswerGenerator):
                    answer = await model.stream_generate(
                        generation_request,
                        _provisional_delta_recorder(
                            session=session,
                            tenant_id=tenant_id,
                            query_run_id=query_run_id,
                        ),
                    )
                else:
                    answer = await model.generate(generation_request)
            except (Exception, asyncio.CancelledError):
                if usage_recorder is not None:
                    await session.rollback()
                raise
            if usage_recorder is not None:
                # Draft-event appends acquire a parent FOR UPDATE lock. Release
                # it before independent finalization/support inserts need FK
                # key-share locks. The events remain explicitly provisional.
                await session.commit()
            return answer

        if clarification is not None:
            if usage_recorder is not None:
                usage_recorder.expected[ProviderUsageOperation.ANSWER] = 0
                usage_recorder.expected[ProviderUsageOperation.FAITHFULNESS] = 0
            draft_answer = GeneratedAnswer(
                text=clarification.text,
                insufficient_context=True,
                metadata={"provider": "scope-policy", "model": clarification_version},
            )
            verification = QueryFaithfulnessResult(
                answer=draft_answer,
                report=AnswerFaithfulnessReport(
                    supported_claim_count=0,
                    unsupported_claim_count=0,
                    abstained=True,
                    abstain_reason=clarification_reason,
                    support_method="scope-policy",
                    metadata={
                        "policy_version": clarification_version,
                        "missing_scope": clarification.missing_scope,
                    },
                ),
            )
            await append_query_run_event(
                session,
                tenant_id=tenant_id,
                query_run_id=query_run_id,
                event_type="query.clarification_required",
                payload={
                    "reason": clarification_reason,
                    "policy_version": clarification_version,
                    "missing_scope": clarification.missing_scope,
                },
            )
        elif usage_recorder is not None:
            # Hint/preparation writes must not retain a writer transaction while
            # a separate session commits the pre-dispatch attempt.
            await session.commit()
            draft_answer = await usage_recorder.invoke(
                generate_draft,
                operation=ProviderUsageOperation.ANSWER,
            )
        else:
            draft_answer = await generate_draft()
        if clarification is None:
            stage = "support_check"
            verification = await verify_generated_answer(
                tenant_id=tenant_id,
                query=query,
                context_pack=context_pack,
                draft_answer=draft_answer,
                support_checker=support_checker,
                usage_recorder=usage_recorder,
                policy=QueryFaithfulnessPolicy(
                    min_supported_claim_ratio=min_supported_claim_ratio,
                    min_context_relevance=min_context_relevance,
                ),
            )
        stage = "persist_answer"
        answer = verification.answer
        faithfulness = faithfulness_summary(verification.report)
        answer_provider = _answer_provider(draft_answer)
        if clarification is None and usage_recorder is None:
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
        if verification.arithmetic_audit is not None:
            # Tenant-owned audit only: never put operand quotations/provider reasons in logs
            # or aggregate telemetry. Claims retain the original draft text separately.
            run.metadata_ = {
                **run.metadata_,
                "arithmetic_verification": verification.arithmetic_audit,
            }
            await session.flush()
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
