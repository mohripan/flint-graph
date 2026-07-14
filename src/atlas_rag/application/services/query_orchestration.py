from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.query_orchestration import (
    QueryCandidate,
    QueryClassification,
    QueryReranker,
)
from atlas_rag.application.services.query_fusion import (
    fuse_query_candidates,
    rerank_fused_query_candidates,
)
from atlas_rag.application.services.query_planning import classify_query_run, link_query_entities
from atlas_rag.application.services.query_runs import (
    append_query_run_event,
    persist_query_candidate,
    transition_query_run,
)
from atlas_rag.domain.enums import QueryRunStatus

RetrieverName = Literal["lexical", "vector", "graph"]


class LexicalRetriever(Protocol):
    async def retrieve_lexical(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        query: str,
        retrieval_index_version_id: UUID,
        limit: int,
    ) -> list[QueryCandidate]: ...


class VectorRetriever(Protocol):
    async def retrieve_vector(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        query: str,
        retrieval_index_version_id: UUID,
        limit: int,
    ) -> list[QueryCandidate]: ...


class GraphRetriever(Protocol):
    async def retrieve_graph(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        query: str,
        retrieval_index_version_id: UUID,
        linked_entity_ids: list[UUID],
        depth: int,
        limit: int,
    ) -> list[QueryCandidate]: ...


@dataclass(frozen=True, slots=True)
class QueryRetrieverBundle:
    lexical: LexicalRetriever | None = None
    vector: VectorRetriever | None = None
    graph: GraphRetriever | None = None


@dataclass(frozen=True, slots=True)
class QueryRetrievalGraphResult:
    query_run_id: UUID
    tenant_id: UUID
    status: QueryRunStatus
    classification_label: str | None
    enabled_retrievers: list[RetrieverName]
    linked_entity_ids: list[UUID]
    retrieved_candidate_count: int
    fused_candidate_count: int
    reranked_candidate_count: int
    errors: list[dict[str, Any]] = field(default_factory=list)


class _GraphState(TypedDict, total=False):
    query_run_id: UUID
    tenant_id: UUID
    query: str
    retrieval_index_version_id: UUID
    status: QueryRunStatus
    classification: QueryClassification
    classification_label: str
    enabled_retrievers: list[RetrieverName]
    candidate_limits: dict[str, int]
    allow_partial_retrieval: bool
    linked_entity_ids: list[UUID]
    retrieved_candidate_count: int
    fused_candidate_count: int
    reranked_candidate_count: int
    errors: list[dict[str, Any]]


async def run_query_retrieval_graph(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
    retrievers: QueryRetrieverBundle,
    reranker: QueryReranker | None = None,
    graph_depth: int = 1,
    rerank_max_results: int = 20,
) -> QueryRetrievalGraphResult:
    graph = _build_retrieval_graph(
        session=session,
        retrievers=retrievers,
        reranker=reranker,
        graph_depth=graph_depth,
        rerank_max_results=rerank_max_results,
    )
    state = await graph.ainvoke(
        {
            "tenant_id": tenant_id,
            "query_run_id": query_run_id,
            "errors": [],
            "enabled_retrievers": [],
            "linked_entity_ids": [],
            "retrieved_candidate_count": 0,
            "fused_candidate_count": 0,
            "reranked_candidate_count": 0,
        }
    )
    return QueryRetrievalGraphResult(
        query_run_id=query_run_id,
        tenant_id=tenant_id,
        status=state["status"],
        classification_label=state.get("classification_label"),
        enabled_retrievers=state.get("enabled_retrievers", []),
        linked_entity_ids=state.get("linked_entity_ids", []),
        retrieved_candidate_count=state.get("retrieved_candidate_count", 0),
        fused_candidate_count=state.get("fused_candidate_count", 0),
        reranked_candidate_count=state.get("reranked_candidate_count", 0),
        errors=state.get("errors", []),
    )


def _build_retrieval_graph(
    *,
    session: AsyncSession,
    retrievers: QueryRetrieverBundle,
    reranker: QueryReranker | None,
    graph_depth: int,
    rerank_max_results: int,
) -> Any:
    builder = StateGraph(_GraphState)

    async def initialize_run(state: _GraphState) -> _GraphState:
        run = await transition_query_run(
            session,
            tenant_id=state["tenant_id"],
            query_run_id=state["query_run_id"],
            target_status=QueryRunStatus.RUNNING,
            event_type="query.started",
            payload={"node": "initialize_run"},
        )
        return {
            "query": run.query_text,
            "retrieval_index_version_id": run.retrieval_index_version_id,
            "status": run.status,
        }

    async def classify(state: _GraphState) -> _GraphState:
        classification = await classify_query_run(
            session,
            tenant_id=state["tenant_id"],
            query_run_id=state["query_run_id"],
        )
        return {
            "classification": classification,
            "classification_label": classification.label,
        }

    async def link_entities(state: _GraphState) -> _GraphState:
        links = await link_query_entities(
            session,
            tenant_id=state["tenant_id"],
            query_run_id=state["query_run_id"],
        )
        accepted = [
            link.canonical_entity_id
            for link in links
            if link.status == "accepted" and link.canonical_entity_id is not None
        ]
        return {"linked_entity_ids": accepted}

    async def plan_retrieval(state: _GraphState) -> _GraphState:
        classification = state["classification"]
        enabled = list(classification.retrieval_plan.enabled_retrievers)
        if "graph" in enabled and not state.get("linked_entity_ids"):
            enabled.remove("graph")
        return {
            "enabled_retrievers": enabled,
            "candidate_limits": {
                str(source): limit
                for source, limit in classification.retrieval_plan.candidate_limits.items()
            },
            "allow_partial_retrieval": classification.retrieval_plan.allow_partial_retrieval,
        }

    async def retrieve_parallel(state: _GraphState) -> _GraphState:
        enabled = state.get("enabled_retrievers", [])
        await append_query_run_event(
            session,
            tenant_id=state["tenant_id"],
            query_run_id=state["query_run_id"],
            event_type="retrieval.started",
            payload={"retrievers": enabled},
        )
        results = await asyncio.gather(
            *[
                _retrieve_source(
                    session=session,
                    state=state,
                    retrievers=retrievers,
                    source=source,
                    graph_depth=graph_depth,
                )
                for source in enabled
            ],
            return_exceptions=True,
        )

        errors: list[dict[str, Any]] = []
        candidate_count = 0
        for source, result in zip(enabled, results, strict=True):
            if isinstance(result, BaseException):
                errors.append(
                    {
                        "source": source,
                        "error_code": "retriever_failed",
                        "error_message": str(result),
                    }
                )
                await append_query_run_event(
                    session,
                    tenant_id=state["tenant_id"],
                    query_run_id=state["query_run_id"],
                    event_type="retrieval.progress",
                    payload={"source": source, "status": "failed", "error": str(result)},
                )
                continue

            for candidate in result:
                await persist_query_candidate(
                    session,
                    tenant_id=state["tenant_id"],
                    query_run_id=state["query_run_id"],
                    candidate=candidate,
                )
            candidate_count += len(result)
            await append_query_run_event(
                session,
                tenant_id=state["tenant_id"],
                query_run_id=state["query_run_id"],
                event_type="retrieval.progress",
                payload={
                    "source": source,
                    "status": "completed",
                    "candidate_count": len(result),
                },
            )

        if errors and not state.get("allow_partial_retrieval", False):
            await transition_query_run(
                session,
                tenant_id=state["tenant_id"],
                query_run_id=state["query_run_id"],
                target_status=QueryRunStatus.FAILED,
                event_type="query.failed",
                payload={"stage": "retrieve_parallel", "errors": errors},
                error_code="retrieval_failed",
                error_message="One or more required retrievers failed.",
                error_details={"errors": errors},
            )
            return {
                "status": QueryRunStatus.FAILED,
                "retrieved_candidate_count": candidate_count,
                "errors": errors,
            }

        await append_query_run_event(
            session,
            tenant_id=state["tenant_id"],
            query_run_id=state["query_run_id"],
            event_type="retrieval.completed",
            payload={
                "candidate_count": candidate_count,
                "failed_retrievers": [error["source"] for error in errors],
            },
        )
        return {
            "status": QueryRunStatus.RUNNING,
            "retrieved_candidate_count": candidate_count,
            "errors": errors,
        }

    async def fuse_candidates(state: _GraphState) -> _GraphState:
        if state.get("status") == QueryRunStatus.FAILED:
            return {}
        result = await fuse_query_candidates(
            session,
            tenant_id=state["tenant_id"],
            query_run_id=state["query_run_id"],
            classification=state["classification"],
        )
        return {"fused_candidate_count": result.fused_candidate_count}

    async def rerank_candidates(state: _GraphState) -> _GraphState:
        if state.get("status") == QueryRunStatus.FAILED:
            return {}
        result = await rerank_fused_query_candidates(
            session,
            tenant_id=state["tenant_id"],
            query_run_id=state["query_run_id"],
            reranker=reranker,
            max_results=rerank_max_results,
        )
        return {"reranked_candidate_count": result.reranked_candidate_count}

    builder.add_node("initialize_run", initialize_run)
    builder.add_node("classify_query", classify)
    builder.add_node("link_entities", link_entities)
    builder.add_node("plan_retrieval", plan_retrieval)
    builder.add_node("retrieve_parallel", retrieve_parallel)
    builder.add_node("fuse_candidates", fuse_candidates)
    builder.add_node("rerank_candidates", rerank_candidates)
    builder.add_edge(START, "initialize_run")
    builder.add_edge("initialize_run", "classify_query")
    builder.add_edge("classify_query", "link_entities")
    builder.add_edge("link_entities", "plan_retrieval")
    builder.add_edge("plan_retrieval", "retrieve_parallel")
    builder.add_edge("retrieve_parallel", "fuse_candidates")
    builder.add_edge("fuse_candidates", "rerank_candidates")
    builder.add_edge("rerank_candidates", END)
    return builder.compile()


async def _retrieve_source(
    *,
    session: AsyncSession,
    state: _GraphState,
    retrievers: QueryRetrieverBundle,
    source: RetrieverName,
    graph_depth: int,
) -> list[QueryCandidate]:
    limit = state.get("candidate_limits", {}).get(source, 10)
    if source == "lexical":
        if retrievers.lexical is None:
            raise RuntimeError("lexical retriever is not configured")
        return await retrievers.lexical.retrieve_lexical(
            session,
            tenant_id=state["tenant_id"],
            query=state["query"],
            retrieval_index_version_id=state["retrieval_index_version_id"],
            limit=limit,
        )
    if source == "vector":
        if retrievers.vector is None:
            raise RuntimeError("vector retriever is not configured")
        return await retrievers.vector.retrieve_vector(
            session,
            tenant_id=state["tenant_id"],
            query=state["query"],
            retrieval_index_version_id=state["retrieval_index_version_id"],
            limit=limit,
        )
    if retrievers.graph is None:
        raise RuntimeError("graph retriever is not configured")
    return await retrievers.graph.retrieve_graph(
        session,
        tenant_id=state["tenant_id"],
        query=state["query"],
        retrieval_index_version_id=state["retrieval_index_version_id"],
        linked_entity_ids=state.get("linked_entity_ids", []),
        depth=graph_depth,
        limit=limit,
    )
