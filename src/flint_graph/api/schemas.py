from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from flint_graph.domain.enums import (
    AliasSource,
    DocumentIndexCoverageStatus,
    DocumentLifecycleEventType,
    DocumentProjectionCleanupStatus,
    DocumentVersionStatus,
    EntityStatus,
    EntityType,
    IndexBackfillJobStatus,
    IngestionJobStatus,
    MentionResolutionStatus,
    MergeDecisionSource,
    MergeDecisionType,
    QueryRunStatus,
    RetrievalIndexScope,
    RetrievalIndexVersionStatus,
    SourceType,
)


class TenantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    

class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    name: str
    created_at: datetime
    
    
class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    source_type: SourceType
    source_uri: str | None = Field(default=None, max_length=4000)
    external_id: str | None = Field(default=None, max_length=500)
    
    @model_validator(mode="after")
    def validate_source_reference(self) -> Self:
        if self.source_type in {SourceType.URL, SourceType.CONNECTOR} and not self.source_uri:
            raise ValueError(f"source_uri is required for source_type '{self.source_type}'.")
        return self
    

class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    tenant_id: UUID
    title: str
    source_type: SourceType
    source_uri: str | None
    external_id: str | None
    created_at: datetime


class URLIntakeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    source_url: str = Field(min_length=1, max_length=4000)
    external_id: str | None = Field(default=None, max_length=500)


class DocumentIntakeResponse(BaseModel):
    document_id: UUID
    document_version_id: UUID
    ingestion_job_id: UUID
    tenant_id: UUID
    title: str
    source_type: SourceType
    source_uri: str | None
    external_id: str | None
    version_number: int
    job_status: IngestionJobStatus
    idempotency_key: str
    object_uri: str
    content_hash: str
    created_at: datetime


class DocumentDeleteResponse(BaseModel):
    document_id: UUID
    deleted_version_ids: list[UUID]
    cleanup_count: int


class DocumentLifecycleEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_id: UUID
    document_version_id: UUID | None
    event_type: DocumentLifecycleEventType
    reason: str | None
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DocumentProjectionCleanupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_id: UUID
    document_version_id: UUID
    retrieval_index_version_id: UUID
    status: DocumentProjectionCleanupStatus
    stale_reason: str
    chunk_count: int
    vector_count: int
    lexical_count: int
    attempt_count: int
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    
    
class IngestionJobResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    document_id: UUID
    document_version_id: UUID
    version_number: int
    status: IngestionJobStatus
    idempotency_key: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None
    

class IngestionJobEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    event_type: str
    from_status: IngestionJobStatus | None
    to_status: IngestionJobStatus
    details: dict[str, Any]
    created_at: datetime
    

class ProblemDetail(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    instance: str
    request_id: str | None = None
    errors: list[dict[str, Any]] | None = None


class CanonicalEntitySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    entity_type: EntityType
    canonical_name: str
    normalized_name: str
    status: EntityStatus
    support_count: int
    merged_into_id: UUID | None


class EntityAliasResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    surface_form: str
    normalized_form: str
    source: AliasSource


class EntityMentionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    document_version_id: UUID
    surface_text: str
    resolution_status: MentionResolutionStatus


class EntityRelationshipSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject_entity_id: UUID
    predicate: str
    object_entity_id: UUID
    support_count: int


class CanonicalEntityDetail(CanonicalEntitySummary):
    aliases: list[EntityAliasResponse]
    mentions: list[EntityMentionSummary]
    relationships: list[EntityRelationshipSummary]


class MergeEntitiesRequest(BaseModel):
    target_entity_id: UUID
    actor: str = Field(default="api", max_length=200)
    reason: str = Field(default="manual merge", min_length=1, max_length=1000)


class UnmergeEntityRequest(BaseModel):
    actor: str = Field(default="api", max_length=200)
    reason: str = Field(default="manual unmerge", min_length=1, max_length=1000)


class EntityMergeResponse(BaseModel):
    source_entity_id: UUID
    target_entity_id: UUID | None
    status: str


class PendingReviewResponse(BaseModel):
    candidate_id: UUID
    mention_id: UUID
    mention_surface: str
    entity_type: str
    target_entity_id: UUID
    target_name: str
    score: float


class ReviewDecisionRequest(BaseModel):
    decision: Literal["accept", "reject"]
    actor: str = Field(default="api", max_length=200)
    reason: str = Field(default="review decision", min_length=1, max_length=1000)


class ReviewDecisionResponse(BaseModel):
    candidate_id: UUID
    decision: str
    status: str


class MergeDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    candidate_id: UUID | None
    decision_type: MergeDecisionType
    source: MergeDecisionSource
    actor: str | None
    reason: str | None
    payload: dict[str, Any]
    decided_at: datetime
    created_at: datetime


class RetrievalIndexVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    scope: RetrievalIndexScope
    tenant_id: UUID | None
    embedding_provider: str
    embedding_model: str
    vector_dimension: int
    embedding_config_hash: str
    chunking_schema_version: str
    chunking_config_hash: str
    lexical_schema_version: str
    neo4j_vector_index_name: str
    neo4j_vector_property_name: str
    opensearch_index_name: str
    opensearch_alias_name: str
    status: RetrievalIndexVersionStatus
    activated_at: datetime | None
    deprecated_at: datetime | None
    failed_at: datetime | None
    error_code: str | None
    error_message: str | None
    metadata_: dict[str, Any] = Field(serialization_alias="metadata")
    created_at: datetime
    updated_at: datetime


class DocumentIndexCoverageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_id: UUID
    document_version_id: UUID
    retrieval_index_version_id: UUID
    status: DocumentIndexCoverageStatus
    chunk_count: int
    embedded_count: int
    vector_count: int
    lexical_count: int
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class SearchReadinessIndexVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    embedding_provider: str
    embedding_model: str
    vector_dimension: int
    opensearch_index_name: str
    neo4j_vector_index_name: str


class SearchReadinessDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: UUID
    document_version_id: UUID
    title: str
    version_number: int
    document_version_status: DocumentVersionStatus
    status: str
    coverage_status: DocumentIndexCoverageStatus | None
    chunk_count: int
    embedded_count: int
    vector_count: int
    lexical_count: int
    error_code: str | None
    error_message: str | None
    updated_at: datetime


class SearchReadinessResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ready: bool
    reason: str
    active_index_version: SearchReadinessIndexVersionResponse | None
    completed_coverage_count: int
    running_coverage_count: int
    failed_coverage_count: int
    cancelled_coverage_count: int
    documents: list[SearchReadinessDocumentResponse]


class IndexBackfillCreateRequest(BaseModel):
    retrieval_index_version_id: UUID
    document_id: UUID | None = None
    document_version_id: UUID | None = None


class IndexBackfillJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    retrieval_index_version_id: UUID
    document_id: UUID | None
    document_version_id: UUID | None
    status: IndexBackfillJobStatus
    total_count: int
    processed_count: int
    failed_count: int
    checkpoint: dict[str, Any]
    last_error: dict[str, Any] | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RetrievalSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=10, ge=1, le=50)
    retrieval_index_version_id: UUID | None = None
    filters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_filters(self) -> Self:
        for name, value in self.filters.items():
            if not isinstance(name, str) or not name:
                raise ValueError("filter names must be non-empty strings.")
            if not isinstance(value, str | int | float | bool):
                raise ValueError("filter values must be strings, numbers, or booleans.")
        return self


class RetrievalChunkResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    score: float
    tenant_id: UUID
    document_id: UUID
    document_version_id: UUID
    chunk_id: str
    chunk_hash: str
    text: str | None
    title: str | None
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    source_uri: str | None
    metadata: dict[str, Any]


class RetrievalSearchResponse(BaseModel):
    index_version_id: UUID
    results: list[RetrievalChunkResultResponse]


class EntityNeighborhoodResponse(BaseModel):
    root_entity_id: UUID
    depth: int
    entities: list[CanonicalEntitySummary]
    relationships: list[EntityRelationshipSummary]


class QueryRunCreateRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    retrieval_index_version_id: UUID | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    stream: bool = True

    @model_validator(mode="after")
    def validate_filters(self) -> Self:
        for name, value in self.filters.items():
            if not isinstance(name, str) or not name:
                raise ValueError("filter names must be non-empty strings.")
            if not isinstance(value, str | int | float | bool):
                raise ValueError("filter values must be strings, numbers, or booleans.")
        return self


class QueryRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    retrieval_index_version_id: UUID
    query_text: str
    status: QueryRunStatus
    classification_label: str | None
    retrieval_strategy: str | None
    classification_confidence: float | None
    classification_metadata: dict[str, Any]
    answer_text: str | None
    answer_citations: list[dict[str, Any]]
    candidate_count: int
    context_token_count: int
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    cancelled_at: datetime | None
    error_code: str | None
    error_message: str | None
    error_details: dict[str, Any]
    query_diagnostics: dict[str, Any]
    metadata_: dict[str, Any] = Field(serialization_alias="metadata")
    created_at: datetime
    updated_at: datetime


class QueryRunEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    query_run_id: UUID
    tenant_id: UUID
    sequence: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


class QueryCitationClaimProvenanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    claim_index: int
    text: str
    support_status: str
    support_score: float
    support_reason: str
    method: str


class QueryCitationProvenanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    claims: list[QueryCitationClaimProvenanceResponse]


class QueryAnswerClaimProvenanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    claim_index: int
    text: str
    citation_ids: list[str]
    support_status: str
    support_score: float
    support_reason: str
    method: str
    citations: list[QueryCitationProvenanceResponse]


class QueryAnswerProvenanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    claims: list[QueryAnswerClaimProvenanceResponse]
    citations: list[QueryCitationProvenanceResponse]
