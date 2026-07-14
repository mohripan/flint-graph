from __future__ import annotations

import json
import re
from typing import Any, Literal, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

QUERY_ORCHESTRATION_CONTRACT_VERSION: Literal["1"] = "1"
MAX_STREAM_EVENT_PAYLOAD_BYTES = 8192
MAX_METADATA_BYTES = 4096

QueryProvider = Literal["deterministic", "ollama"]
QueryRunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
QueryLabel = Literal[
    "factoid",
    "summary",
    "relationship",
    "comparison",
    "exploratory",
    "unsupported",
]
RetrieverSource = Literal["lexical", "vector", "graph"]
CandidateType = Literal["chunk", "entity", "relationship", "evidence_span"]
EntityLinkStatus = Literal["accepted", "ambiguous", "rejected"]
SupportStatus = Literal["supported", "partial", "unsupported"]
CitationRepairAction = Literal["kept", "normalized", "dropped_unknown", "deduplicated"]
QueryStreamEventType = Literal[
    "query.started",
    "query.classified",
    "entities.linked",
    "retrieval.started",
    "retrieval.progress",
    "retrieval.completed",
    "fusion.completed",
    "graph.expanded",
    "rerank.completed",
    "context.packed",
    "answer.delta",
    "answer.citation",
    "query.completed",
    "query.failed",
    "query.cancelled",
]

_WORD_RE = re.compile(r"[a-z0-9]+")


class QueryRetrievalPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy: str = Field(min_length=1, max_length=100)
    enabled_retrievers: list[RetrieverSource] = Field(min_length=1, max_length=3)
    retriever_weights: dict[RetrieverSource, float] = Field(default_factory=dict)
    candidate_limits: dict[RetrieverSource, int] = Field(default_factory=dict)
    requires_entity_linking: bool = False
    requires_graph_expansion: bool = False
    allow_partial_retrieval: bool = False

    @model_validator(mode="after")
    def _validate_enabled_retrievers(self) -> Self:
        seen: set[RetrieverSource] = set()
        for retriever in self.enabled_retrievers:
            if retriever in seen:
                raise ValueError(f"duplicate retriever '{retriever}'")
            seen.add(retriever)
            if retriever not in self.retriever_weights:
                raise ValueError(f"missing weight for retriever '{retriever}'")
            if retriever not in self.candidate_limits:
                raise ValueError(f"missing candidate limit for retriever '{retriever}'")
            if self.candidate_limits[retriever] < 1:
                raise ValueError("candidate limits must be positive")

        for retriever, weight in self.retriever_weights.items():
            if retriever not in seen:
                raise ValueError(f"weight configured for disabled retriever '{retriever}'")
            if not 0.0 <= weight <= 1.0:
                raise ValueError("retriever weights must be between 0 and 1")

        if sum(self.retriever_weights.values()) <= 0:
            raise ValueError("at least one retriever weight must be positive")
        return self


class QueryClassificationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: UUID
    query: str = Field(min_length=1, max_length=1000)
    retrieval_index_version_id: UUID | None = None
    metadata_filters: dict[str, Any] = Field(default_factory=dict)
    max_candidate_limit: int = Field(default=50, ge=1, le=500)

    @model_validator(mode="after")
    def _validate_metadata_filters(self) -> Self:
        _validate_json_size("metadata filters", self.metadata_filters, MAX_METADATA_BYTES)
        return self


class QueryClassification(BaseModel):
    model_config = ConfigDict(frozen=True)

    contract_version: Literal["1"] = QUERY_ORCHESTRATION_CONTRACT_VERSION
    label: QueryLabel
    confidence: float = Field(ge=0.0, le=1.0)
    retrieval_plan: QueryRetrievalPlan
    reasons: list[str] = Field(default_factory=list, max_length=10)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_metadata_size(self) -> Self:
        _validate_json_size("metadata", self.metadata, MAX_METADATA_BYTES)
        return self


class QueryEntityLink(BaseModel):
    model_config = ConfigDict(frozen=True)

    mention_text: str = Field(min_length=1, max_length=500)
    status: EntityLinkStatus
    score: float = Field(ge=0.0, le=1.0)
    method: str = Field(min_length=1, max_length=100)
    canonical_entity_id: UUID | None = None
    candidate_entity_ids: list[UUID] = Field(default_factory=list, max_length=20)
    reasons: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _validate_link_target(self) -> Self:
        if self.status == "accepted" and self.canonical_entity_id is None:
            raise ValueError("accepted entity links require a canonical_entity_id")
        if self.status == "ambiguous" and not self.candidate_entity_ids:
            raise ValueError("ambiguous entity links require candidate_entity_ids")
        return self


class QueryCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str = Field(min_length=1, max_length=300)
    source: RetrieverSource
    candidate_type: CandidateType
    tenant_id: UUID
    retrieval_index_version_id: UUID | None = None
    source_ids: dict[str, str] = Field(min_length=1, max_length=20)
    text_preview: str | None = Field(default=None, max_length=2000)
    raw_score: float
    normalized_score: float = Field(ge=0.0, le=1.0)
    rank: int = Field(ge=1)
    fusion_score: float | None = Field(default=None, ge=0.0)
    rerank_score: float | None = Field(default=None, ge=0.0)
    rerank_rank: int | None = Field(default=None, ge=1)
    reasons: list[str] = Field(default_factory=list, max_length=10)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_bounded_metadata(self) -> Self:
        _validate_json_size("source ids", self.source_ids, MAX_METADATA_BYTES)
        _validate_json_size("metadata", self.metadata, MAX_METADATA_BYTES)
        return self


class QueryRerankRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str = Field(min_length=1, max_length=1000)
    candidates: list[QueryCandidate] = Field(min_length=1, max_length=200)
    max_results: int = Field(default=20, ge=1, le=200)

    @model_validator(mode="after")
    def _validate_max_results(self) -> Self:
        if self.max_results > len(self.candidates):
            raise ValueError("max_results cannot exceed candidate count")
        return self


class QueryRerankResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidates: list[QueryCandidate] = Field(default_factory=list, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PackedContextRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    context_id: str = Field(min_length=1, max_length=200)
    candidate_id: str = Field(min_length=1, max_length=300)
    citation_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=4000)
    token_count: int = Field(ge=0)
    source_ids: dict[str, str] = Field(min_length=1, max_length=20)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_bounded_metadata(self) -> Self:
        _validate_json_size("source ids", self.source_ids, MAX_METADATA_BYTES)
        _validate_json_size("metadata", self.metadata, MAX_METADATA_BYTES)
        return self


class QueryContextPack(BaseModel):
    model_config = ConfigDict(frozen=True)

    pack_id: str = Field(min_length=1, max_length=200)
    pack_version: int = Field(default=1, ge=1)
    token_budget: int = Field(ge=1)
    records: list[PackedContextRecord] = Field(default_factory=list, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_records(self) -> Self:
        if sum(record.token_count for record in self.records) > self.token_budget:
            raise ValueError("context pack exceeds token budget")
        citation_ids: set[str] = set()
        context_ids: set[str] = set()
        for record in self.records:
            if record.citation_id in citation_ids:
                raise ValueError(f"duplicate citation id '{record.citation_id}'")
            citation_ids.add(record.citation_id)
            if record.context_id in context_ids:
                raise ValueError(f"duplicate context id '{record.context_id}'")
            context_ids.add(record.context_id)
        _validate_json_size("metadata", self.metadata, MAX_METADATA_BYTES)
        return self


class AnswerCitation(BaseModel):
    model_config = ConfigDict(frozen=True)

    citation_id: str = Field(min_length=1, max_length=100)
    context_id: str = Field(min_length=1, max_length=200)
    marker: str = Field(min_length=1, max_length=50)
    source_ids: dict[str, str] = Field(min_length=1, max_length=20)


class GeneratedAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1, max_length=16000)
    citations: list[AnswerCitation] = Field(default_factory=list, max_length=100)
    insufficient_context: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_bounded_metadata(self) -> Self:
        _validate_json_size("metadata", self.metadata, MAX_METADATA_BYTES)
        return self


class AnswerDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1, max_length=16000)
    raw_citation_markers: list[str] = Field(default_factory=list, max_length=100)
    insufficient_context: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_bounded_metadata(self) -> Self:
        _validate_json_size("metadata", self.metadata, MAX_METADATA_BYTES)
        return self


class CitationRepair(BaseModel):
    model_config = ConfigDict(frozen=True)

    original_marker: str = Field(min_length=1, max_length=100)
    resolved_citation_id: str | None = Field(default=None, max_length=100)
    action: CitationRepairAction
    reason: str = Field(min_length=1, max_length=500)


class SupportCheckClaim(BaseModel):
    model_config = ConfigDict(frozen=True)

    claim_index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=4000)
    citation_ids: list[str] = Field(default_factory=list, max_length=100)


class AnswerClaim(BaseModel):
    model_config = ConfigDict(frozen=True)

    claim_index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=4000)
    citation_ids: list[str] = Field(default_factory=list, max_length=100)
    support_status: SupportStatus
    support_score: float = Field(ge=0.0, le=1.0)
    support_reason: str = Field(min_length=1, max_length=1000)
    method: str = Field(min_length=1, max_length=100)


class AnswerFaithfulnessReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    claims: list[AnswerClaim] = Field(default_factory=list, max_length=100)
    repairs: list[CitationRepair] = Field(default_factory=list, max_length=200)
    supported_claim_count: int = Field(ge=0)
    unsupported_claim_count: int = Field(ge=0)
    abstained: bool
    abstain_reason: str | None = Field(default=None, max_length=500)
    support_method: str = Field(min_length=1, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_bounded_metadata(self) -> Self:
        _validate_json_size("metadata", self.metadata, MAX_METADATA_BYTES)
        return self


class AnswerGenerationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: UUID
    query: str = Field(min_length=1, max_length=1000)
    retrieval_index_version_id: UUID
    context_pack: QueryContextPack
    policy: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_policy_size(self) -> Self:
        _validate_json_size("policy", self.policy, MAX_METADATA_BYTES)
        return self


class QueryStreamEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_type: QueryStreamEventType
    payload: dict[str, Any] = Field(default_factory=dict)
    sequence: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _validate_payload_size(self) -> Self:
        _validate_json_size("payload", self.payload, MAX_STREAM_EVENT_PAYLOAD_BYTES)
        return self


class SupportCheckRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: UUID
    query: str = Field(min_length=1, max_length=1000)
    context_pack: QueryContextPack
    claims: list[SupportCheckClaim] = Field(default_factory=list, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_bounded_metadata(self) -> Self:
        _validate_json_size("metadata", self.metadata, MAX_METADATA_BYTES)
        return self


class SupportCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    claims: list[AnswerClaim] = Field(default_factory=list, max_length=100)
    method: str = Field(min_length=1, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_bounded_metadata(self) -> Self:
        _validate_json_size("metadata", self.metadata, MAX_METADATA_BYTES)
        return self


class QueryClassifier(Protocol):
    async def classify(self, request: QueryClassificationRequest) -> QueryClassification: ...


class QueryReranker(Protocol):
    async def rerank(self, request: QueryRerankRequest) -> QueryRerankResult: ...


class AnswerGenerator(Protocol):
    async def generate(self, request: AnswerGenerationRequest) -> GeneratedAnswer: ...


class SupportChecker(Protocol):
    async def check(self, request: SupportCheckRequest) -> SupportCheckResult: ...


class DeterministicQueryClassifier:
    async def classify(self, request: QueryClassificationRequest) -> QueryClassification:
        query = request.query.casefold()
        if any(term in query for term in ("ignore instructions", "jailbreak", "secret key")):
            return _classification(
                label="unsupported",
                confidence=0.9,
                strategy="unsupported",
                enabled_retrievers=["lexical"],
                weights={"lexical": 1.0},
                limits={"lexical": 1},
                reasons=["unsupported safety or scope cue"],
            )
        if any(term in query for term in ("connected", "relationship", "relate", "between")):
            return _classification(
                label="relationship",
                confidence=0.85,
                strategy="graph_relationship",
                enabled_retrievers=["lexical", "vector", "graph"],
                weights={"lexical": 0.25, "vector": 0.25, "graph": 0.5},
                limits={"lexical": 10, "vector": 10, "graph": 10},
                requires_entity_linking=True,
                requires_graph_expansion=True,
                reasons=["relationship cue"],
            )
        if any(term in query for term in ("compare", "versus", "difference")):
            return _classification(
                label="comparison",
                confidence=0.8,
                strategy="comparative_retrieval",
                enabled_retrievers=["lexical", "vector", "graph"],
                weights={"lexical": 0.35, "vector": 0.35, "graph": 0.3},
                limits={"lexical": 12, "vector": 12, "graph": 8},
                requires_entity_linking=True,
                requires_graph_expansion=True,
                allow_partial_retrieval=True,
                reasons=["comparison cue"],
            )
        if any(term in query for term in ("summarize", "summary", "overview")):
            return _classification(
                label="summary",
                confidence=0.8,
                strategy="broad_synthesis",
                enabled_retrievers=["lexical", "vector"],
                weights={"lexical": 0.4, "vector": 0.6},
                limits={"lexical": 15, "vector": 15},
                allow_partial_retrieval=True,
                reasons=["summary cue"],
            )
        if any(term in query for term in ("explore", "what do we know", "tell me about")):
            return _classification(
                label="exploratory",
                confidence=0.75,
                strategy="high_recall",
                enabled_retrievers=["lexical", "vector", "graph"],
                weights={"lexical": 0.3, "vector": 0.5, "graph": 0.2},
                limits={"lexical": 20, "vector": 20, "graph": 10},
                requires_entity_linking=True,
                allow_partial_retrieval=True,
                reasons=["exploratory cue"],
            )
        return _classification(
            label="factoid",
            confidence=0.75,
            strategy="focused_answer",
            enabled_retrievers=["lexical", "vector"],
            weights={"lexical": 0.5, "vector": 0.5},
            limits={
                "lexical": min(10, request.max_candidate_limit),
                "vector": min(10, request.max_candidate_limit),
            },
            reasons=["default focused query"],
        )


class DeterministicQueryReranker:
    async def rerank(self, request: QueryRerankRequest) -> QueryRerankResult:
        query_terms = _terms(request.query)
        scored: list[tuple[float, QueryCandidate]] = []
        for candidate in request.candidates:
            candidate_terms = _terms(candidate.text_preview or "")
            overlap = len(query_terms & candidate_terms)
            score = float(overlap) + candidate.normalized_score
            scored.append((score, candidate))

        ordered = sorted(
            scored,
            key=lambda item: (-item[0], -item[1].normalized_score, item[1].candidate_id),
        )
        reranked = [
            candidate.model_copy(
                update={
                    "rerank_score": score,
                    "rerank_rank": rank,
                    "reasons": [*candidate.reasons, "deterministic term-overlap rerank"],
                }
            )
            for rank, (score, candidate) in enumerate(ordered[: request.max_results], start=1)
        ]
        return QueryRerankResult(
            candidates=reranked,
            metadata={"algorithm": "term-overlap-plus-normalized-score"},
        )


class DeterministicAnswerGenerator:
    async def generate(self, request: AnswerGenerationRequest) -> GeneratedAnswer:
        if not request.context_pack.records:
            return GeneratedAnswer(
                text="The available context is insufficient to answer this query.",
                insufficient_context=True,
                metadata={"algorithm": "deterministic-first-context-sentence"},
            )

        first_record = request.context_pack.records[0]
        sentence = _first_sentence(first_record.text)
        citations = [
            AnswerCitation(
                citation_id=record.citation_id,
                context_id=record.context_id,
                marker=f"[{record.citation_id}]",
                source_ids=record.source_ids,
            )
            for record in request.context_pack.records
        ]
        return GeneratedAnswer(
            text=f"{sentence} [{first_record.citation_id}]",
            citations=citations,
            metadata={"algorithm": "deterministic-first-context-sentence"},
        )


def _classification(
    *,
    label: QueryLabel,
    confidence: float,
    strategy: str,
    enabled_retrievers: list[RetrieverSource],
    weights: dict[RetrieverSource, float],
    limits: dict[RetrieverSource, int],
    requires_entity_linking: bool = False,
    requires_graph_expansion: bool = False,
    allow_partial_retrieval: bool = False,
    reasons: list[str],
) -> QueryClassification:
    return QueryClassification(
        label=label,
        confidence=confidence,
        retrieval_plan=QueryRetrievalPlan(
            strategy=strategy,
            enabled_retrievers=enabled_retrievers,
            retriever_weights=weights,
            candidate_limits=limits,
            requires_entity_linking=requires_entity_linking,
            requires_graph_expansion=requires_graph_expansion,
            allow_partial_retrieval=allow_partial_retrieval,
        ),
        reasons=reasons,
        metadata={"provider": "deterministic"},
    )


def _terms(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.casefold()))


def _first_sentence(text: str) -> str:
    first = text.strip().split(".", maxsplit=1)[0].strip()
    if not first:
        return text.strip()
    return f"{first}."


def _validate_json_size(name: str, value: Any, limit: int) -> None:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    if len(encoded) > limit:
        raise ValueError(f"{name} exceeds {limit} bytes")
