from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from atlas_rag.domain.enums import (
    AliasSource,
    EntityStatus,
    EntityType,
    IngestionJobStatus,
    MentionResolutionStatus,
    MergeDecisionSource,
    MergeDecisionType,
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
