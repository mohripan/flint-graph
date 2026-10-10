from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest

from flint_graph.application.query_orchestration import (
    AnswerClaim,
    AnswerFaithfulnessReport,
    PackedContextRecord,
    QueryContextPack,
)
from flint_graph.application.services.conversation_memory import prepare_conversation_context
from flint_graph.application.services.conversations import (
    ConversationTurnCreate,
    create_conversation,
    create_conversation_turn,
)
from flint_graph.application.services.query_runs import (
    get_query_run,
    persist_query_answer_claims,
    persist_query_context_pack,
    transition_query_run,
)
from flint_graph.application.services.retrieval_bootstrap import bootstrap_retrieval_index
from flint_graph.application.services.retrieval_index_versions import (
    deprecate_retrieval_index_version,
)
from flint_graph.config import Settings
from flint_graph.domain.enums import (
    DocumentIndexCoverageStatus,
    DocumentVersionStatus,
    QueryRunStatus,
    SourceType,
)
from flint_graph.infrastructure.db.models import (
    Document,
    DocumentChunk,
    DocumentIndexCoverage,
    DocumentVersion,
    Tenant,
)


async def grounded_previous_turn(session):
    tenant = Tenant(name=f"memory-{uuid4()}")
    session.add(tenant)
    await session.flush()
    index = await bootstrap_retrieval_index(
        session, tenant_id=tenant.id, settings=Settings(env="test")
    )
    document = Document(tenant_id=tenant.id, title="Acme report", source_type=SourceType.UPLOAD)
    session.add(document)
    await session.flush()
    version = DocumentVersion(
        document_id=document.id, version_number=1, status=DocumentVersionStatus.ACTIVE
    )
    session.add(version)
    await session.flush()
    source = "Acme revenue was 100 million USD in 2017 and 90 million USD in 2016."
    chunk = DocumentChunk(
        tenant_id=tenant.id,
        document_id=document.id,
        document_version_id=version.id,
        chunk_id="memory-source",
        chunk_index=0,
        text=source,
        chunk_hash="sha256:" + sha256(source.encode()).hexdigest(),
    )
    session.add(chunk)
    session.add(
        DocumentIndexCoverage(
            tenant_id=tenant.id,
            document_id=document.id,
            document_version_id=version.id,
            retrieval_index_version_id=index.id,
            status=DocumentIndexCoverageStatus.COMPLETED,
            chunk_count=1,
            embedded_count=1,
            lexical_count=1,
            vector_count=1,
        )
    )
    await session.flush()
    conversation = await create_conversation(session, tenant_id=tenant.id, title="Revenue research")
    previous = await create_conversation_turn(
        session,
        tenant_id=tenant.id,
        conversation_id=conversation.id,
        spec=ConversationTurnCreate(
            query="What was Acme revenue in 2017?", idempotency_key=uuid4()
        ),
    )
    await prepare_conversation_context(
        session, tenant_id=tenant.id, query_run_id=previous.run.id, policy_fingerprint="f" * 64
    )
    source_ids = {
        "document_id": str(document.id),
        "document_version_id": str(version.id),
        "chunk_id": chunk.chunk_id,
    }
    await persist_query_context_pack(
        session,
        tenant_id=tenant.id,
        query_run_id=previous.run.id,
        context_pack=QueryContextPack(
            pack_id="memory-pack",
            token_budget=100,
            records=[
                PackedContextRecord(
                    context_id="memory-context",
                    candidate_id="lexical:memory-source",
                    citation_id="c1",
                    text=source,
                    token_count=20,
                    source_ids=source_ids,
                    metadata={
                        "chunk_hash": chunk.chunk_hash,
                        "evidence_origin": "postgresql_chunk",
                    },
                )
            ],
        ),
    )
    await persist_query_answer_claims(
        session,
        tenant_id=tenant.id,
        query_run_id=previous.run.id,
        report=AnswerFaithfulnessReport(
            claims=[
                AnswerClaim(
                    claim_index=0,
                    text="Acme revenue was 100 million USD in 2017.",
                    citation_ids=["c1"],
                    support_status="supported",
                    support_score=1,
                    support_reason="Explicit fixture source",
                    method="deterministic",
                )
            ],
            supported_claim_count=1,
            unsupported_claim_count=0,
            abstained=False,
            support_method="deterministic",
        ),
    )
    await transition_query_run(
        session,
        tenant_id=tenant.id,
        query_run_id=previous.run.id,
        target_status=QueryRunStatus.RUNNING,
        event_type="query.started",
        payload={},
    )
    await transition_query_run(
        session,
        tenant_id=tenant.id,
        query_run_id=previous.run.id,
        target_status=QueryRunStatus.COMPLETED,
        event_type="query.completed",
        payload={},
        answer_text="Acme revenue was 100 million USD in 2017. [c1]",
        answer_citations=[
            {
                "citation_id": "c1",
                "context_id": "memory-context",
                "marker": "[c1]",
                "source_ids": source_ids,
            }
        ],
        supported_claim_count=1,
        unsupported_claim_count=0,
        abstained=False,
        answer_provider="deterministic",
    )
    await session.commit()
    return tenant, conversation, previous, document, version, chunk


@pytest.mark.anyio
async def test_followup_uses_only_a_revalidated_grounded_previous_question(extraction_db_session):
    session = extraction_db_session
    tenant, conversation, previous, _, _, _ = await grounded_previous_turn(session)
    current = await create_conversation_turn(
        session,
        tenant_id=tenant.id,
        conversation_id=conversation.id,
        spec=ConversationTurnCreate(query="What about the prior year?", idempotency_key=uuid4()),
    )
    result = await prepare_conversation_context(
        session,
        tenant_id=tenant.id,
        query_run_id=current.run.id,
        policy_fingerprint="f" * 64,
    )
    assert result.mode == "resolved"
    assert result.query == "What was Acme revenue in 2016?"
    run = await get_query_run(session, tenant_id=tenant.id, query_run_id=current.run.id)
    assert run.query_text == "What about the prior year?"
    assert run.metadata_["conversation_context"]["previous_run_id"] == str(previous.run.id)
    assert run.metadata_["conversation_context"]["considered_turn_count"] == 1
    assert "100 million" not in str(run.metadata_["conversation_context"])


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fault",
    [
        "deleted",
        "version",
        "chunk_hash",
        "chunk_text",
        "abstained",
        "failed",
        "unsupported",
        "policy",
        "legacy",
        "index",
        "inactive_index",
        "cancelled",
        "filters",
        "latest_pack",
    ],
)
async def test_stale_or_untrusted_previous_turn_cannot_supply_scope(extraction_db_session, fault):
    session = extraction_db_session
    tenant, conversation, previous, document, version, chunk = await grounded_previous_turn(session)
    current = await create_conversation_turn(
        session,
        tenant_id=tenant.id,
        conversation_id=conversation.id,
        spec=ConversationTurnCreate(query="What about the prior year?", idempotency_key=uuid4()),
    )
    if fault == "deleted":
        document.deleted_at = datetime.now(UTC)
    elif fault == "version":
        version.status = DocumentVersionStatus.DELETED
    elif fault == "chunk_hash":
        chunk.chunk_hash = "sha256:" + "a" * 64
    elif fault == "chunk_text":
        chunk.text = "A substituted source with unrelated content."
    elif fault == "abstained":
        previous.run.abstained = True
    elif fault == "failed":
        previous.run.status = QueryRunStatus.FAILED
    elif fault == "cancelled":
        previous.run.status = QueryRunStatus.CANCELLED
    elif fault == "unsupported":
        previous.run.unsupported_claim_count = 1
    elif fault == "legacy":
        previous.run.metadata_ = {}
    elif fault == "index":
        changed = await bootstrap_retrieval_index(
            session,
            tenant_id=tenant.id,
            settings=Settings(env="test", embedding_model="changed"),
        )
        current.run.retrieval_index_version_id = changed.id
    elif fault == "inactive_index":
        await deprecate_retrieval_index_version(
            session, version_id=current.run.retrieval_index_version_id
        )
    elif fault == "filters":
        current.run.metadata_ = {
            **current.run.metadata_,
            "filters": {"document_id": str(document.id)},
        }
    elif fault == "latest_pack":
        await persist_query_context_pack(
            session,
            tenant_id=tenant.id,
            query_run_id=previous.run.id,
            context_pack=QueryContextPack(
                pack_id="memory-pack",
                pack_version=2,
                token_budget=100,
                records=[
                    PackedContextRecord(
                        context_id="memory-context",
                        candidate_id="lexical:memory-source",
                        citation_id="c1",
                        text="Unrelated replacement pack content.",
                        token_count=5,
                        source_ids=previous.run.answer_citations[0]["source_ids"],
                        metadata={
                            "chunk_hash": chunk.chunk_hash,
                            "evidence_origin": "postgresql_chunk",
                        },
                    )
                ],
            ),
        )
    await session.flush()
    result = await prepare_conversation_context(
        session,
        tenant_id=tenant.id,
        query_run_id=current.run.id,
        policy_fingerprint=("e" * 64 if fault == "policy" else "f" * 64),
    )
    assert result.mode == "clarification"
    assert result.query == "What about the prior year?"


@pytest.mark.anyio
async def test_new_conversation_has_no_previous_scope(extraction_db_session):
    session = extraction_db_session
    tenant, _, _, _, _, _ = await grounded_previous_turn(session)
    other = await create_conversation(session, tenant_id=tenant.id, title="New research")
    turn = await create_conversation_turn(
        session,
        tenant_id=tenant.id,
        conversation_id=other.id,
        spec=ConversationTurnCreate(query="What about the prior year?", idempotency_key=uuid4()),
    )
    result = await prepare_conversation_context(
        session,
        tenant_id=tenant.id,
        query_run_id=turn.run.id,
        policy_fingerprint="f" * 64,
    )
    assert result.mode == "clarification"
    assert turn.run.metadata_["conversation_context"]["previous_run_id"] is None


@pytest.mark.anyio
async def test_cancelled_immediate_turn_does_not_fall_back_to_older_grounded_scope(
    extraction_db_session,
):
    session = extraction_db_session
    tenant, conversation, _, _, _, _ = await grounded_previous_turn(session)
    cancelled = await create_conversation_turn(
        session,
        tenant_id=tenant.id,
        conversation_id=conversation.id,
        spec=ConversationTurnCreate(query="Where is Beta headquartered?", idempotency_key=uuid4()),
    )
    await transition_query_run(
        session,
        tenant_id=tenant.id,
        query_run_id=cancelled.run.id,
        target_status=QueryRunStatus.CANCELLED,
        event_type="query.cancelled",
        payload={},
    )
    current = await create_conversation_turn(
        session,
        tenant_id=tenant.id,
        conversation_id=conversation.id,
        spec=ConversationTurnCreate(query="What about the prior year?", idempotency_key=uuid4()),
    )
    result = await prepare_conversation_context(
        session,
        tenant_id=tenant.id,
        query_run_id=current.run.id,
        policy_fingerprint="f" * 64,
    )
    assert result.mode == "clarification"
    context = current.run.metadata_["conversation_context"]
    assert context["previous_run_id"] == str(cancelled.run.id)
    assert context["considered_turn_count"] == context["omitted_turn_count"] == 1
