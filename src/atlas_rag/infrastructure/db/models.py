from datetime import datetime
from enum import Enum as PyEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from atlas_rag.domain.enums import (
    AliasSource,
    CandidateOutcome,
    CandidateTargetKind,
    ClaimStatus,
    DocumentArtifactType,
    DocumentVersionStatus,
    EntityStatus,
    EntityType,
    ExtractionInvocationStatus,
    ExtractionRunStatus,
    IngestionJobStatus,
    MentionResolutionStatus,
    MergeCandidateBand,
    MergeCandidateStatus,
    MergeDecisionSource,
    MergeDecisionType,
    OutboxMessageStatus,
    RelationshipStatus,
    SourceType,
    StagedProposalStatus,
)
from atlas_rag.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def enum_column(enum_type: type[PyEnum], length: int) -> SAEnum:
    return SAEnum(
        enum_type,
        values_callable=lambda members: [member.value for member in members],
        native_enum=False,
        validate_strings=True,
        length=length,
    )


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id", name="uq_documents_tenant_external_id"),
        Index("ix_documents_tenant_created_at", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[SourceType] = mapped_column(enum_column(SourceType, 32), nullable=False)
    source_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_document_versions_number"),
        Index("ix_document_versions_document_status", "document_id", "status"),
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[DocumentVersionStatus] = mapped_column(
        enum_column(DocumentVersionStatus, 32),
        nullable=False,
        default=DocumentVersionStatus.PENDING,
    )
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    object_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )

    document: Mapped[Document] = relationship(back_populates="versions")


class DocumentArtifact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id",
            "artifact_type",
            name="uq_document_artifacts_version_type",
        ),
        Index("ix_document_artifacts_document_version", "document_version_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_type: Mapped[DocumentArtifactType] = mapped_column(
        enum_column(DocumentArtifactType, 32),
        nullable=False,
    )
    object_uri: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


class DocumentChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id",
            "chunk_index",
            name="uq_document_chunks_version_index",
        ),
        UniqueConstraint(
            "document_version_id",
            "chunk_id",
            name="uq_document_chunks_version_chunk_id",
        ),
        Index("ix_document_chunks_document_version", "document_version_id", "chunk_index"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_id: Mapped[str] = mapped_column(String(100), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    source_element_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    heading_path: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_offsets: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


class IngestionJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        UniqueConstraint("document_version_id"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_jobs_tenant_idempotency"),
        Index("ix_jobs_tenant_status_created", "tenant_id", "status", "created_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[IngestionJobStatus] = mapped_column(
        enum_column(IngestionJobStatus, 32),
        nullable=False,
        default=IngestionJobStatus.QUEUED,
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    events: Mapped[list["IngestionJobEvent"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="IngestionJobEvent.created_at"
    )


class IngestionJobEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ingestion_job_events"
    __table_args__ = (Index("ix_job_events_job_created", "job_id", "created_at"),)

    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    from_status: Mapped[IngestionJobStatus | None] = mapped_column(
        enum_column(IngestionJobStatus, 32), nullable=True
    )
    to_status: Mapped[IngestionJobStatus] = mapped_column(
        enum_column(IngestionJobStatus, 32), nullable=False
    )
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    job: Mapped[IngestionJob] = relationship(back_populates="events")


class OutboxMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (
        Index("ix_outbox_status_available", "status", "available_at"),
        Index("ix_outbox_aggregate", "aggregate_type", "aggregate_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    headers: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[OutboxMessageStatus] = mapped_column(
        enum_column(OutboxMessageStatus, 32),
        nullable=False,
        default=OutboxMessageStatus.PENDING,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class CanonicalEntity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "canonical_entities"
    __table_args__ = (
        Index(
            "ix_canonical_entities_tenant_type_name",
            "tenant_id",
            "entity_type",
            "normalized_name",
        ),
        Index("ix_canonical_entities_tenant_status", "tenant_id", "status"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type: Mapped[EntityType] = mapped_column(enum_column(EntityType, 32), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[EntityStatus] = mapped_column(
        enum_column(EntityStatus, 32), nullable=False, default=EntityStatus.ACTIVE
    )
    merged_into_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("canonical_entities.id", ondelete="SET NULL"), nullable=True
    )
    support_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


class EntityAlias(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "entity_aliases"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "canonical_entity_id",
            "normalized_form",
            name="uq_entity_aliases_entity_form",
        ),
        Index("ix_entity_aliases_tenant_form", "tenant_id", "normalized_form"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    canonical_entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    surface_form: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_form: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[AliasSource] = mapped_column(
        enum_column(AliasSource, 32), nullable=False, default=AliasSource.EXTRACTION
    )


class EntityMention(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "entity_mentions"
    __table_args__ = (
        Index("ix_entity_mentions_document_version", "document_version_id"),
        Index("ix_entity_mentions_tenant_status", "tenant_id", "resolution_status"),
        Index(
            "ix_entity_mentions_tenant_type_text", "tenant_id", "entity_type", "normalized_text"
        ),
        Index("ix_entity_mentions_resolved_entity", "resolved_entity_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_artifacts.id", ondelete="SET NULL"), nullable=True
    )
    surface_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(String(500), nullable=False)
    entity_type: Mapped[EntityType] = mapped_column(enum_column(EntityType, 32), nullable=False)
    chunk_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    resolved_entity_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("canonical_entities.id", ondelete="SET NULL"), nullable=True
    )
    resolution_status: Mapped[MentionResolutionStatus] = mapped_column(
        enum_column(MentionResolutionStatus, 32),
        nullable=False,
        default=MentionResolutionStatus.PENDING,
    )
    prompt_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    response_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


class Claim(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "claims"
    __table_args__ = (
        Index("ix_claims_document_version", "tenant_id", "document_version_id"),
        Index("ix_claims_subject_mention", "subject_mention_id"),
        Index("ix_claims_object_mention", "object_mention_id"),
        Index("ix_claims_tenant_status", "tenant_id", "status"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_mention_id: Mapped[UUID] = mapped_column(
        ForeignKey("entity_mentions.id", ondelete="CASCADE"), nullable=False
    )
    predicate: Mapped[str] = mapped_column(String(200), nullable=False)
    object_mention_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("entity_mentions.id", ondelete="CASCADE"), nullable=True
    )
    object_literal: Mapped[str | None] = mapped_column(Text, nullable=True)
    claim_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_chunk_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[ClaimStatus] = mapped_column(
        enum_column(ClaimStatus, 32), nullable=False, default=ClaimStatus.PENDING
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


class EntityRelationship(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "entity_relationships"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "subject_entity_id",
            "predicate",
            "object_entity_id",
            name="uq_entity_relationships_triple",
        ),
        Index("ix_entity_relationships_subject", "subject_entity_id"),
        Index("ix_entity_relationships_object", "object_entity_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_entities.id", ondelete="CASCADE"), nullable=False
    )
    predicate: Mapped[str] = mapped_column(String(200), nullable=False)
    object_entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_entities.id", ondelete="CASCADE"), nullable=False
    )
    support_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provenance: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[RelationshipStatus] = mapped_column(
        enum_column(RelationshipStatus, 32),
        nullable=False,
        default=RelationshipStatus.ACTIVE,
    )


class MergeCandidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "merge_candidates"
    __table_args__ = (
        Index("ix_merge_candidates_tenant_status", "tenant_id", "status"),
        Index("ix_merge_candidates_target", "target_entity_id"),
        Index("ix_merge_candidates_mention", "mention_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mention_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("entity_mentions.id", ondelete="CASCADE"), nullable=True
    )
    source_entity_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("canonical_entities.id", ondelete="CASCADE"), nullable=True
    )
    target_entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_entities.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    features: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    band: Mapped[MergeCandidateBand] = mapped_column(
        enum_column(MergeCandidateBand, 32), nullable=False
    )
    status: Mapped[MergeCandidateStatus] = mapped_column(
        enum_column(MergeCandidateStatus, 32),
        nullable=False,
        default=MergeCandidateStatus.PENDING,
    )


class MergeDecision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "merge_decisions"
    __table_args__ = (
        Index("ix_merge_decisions_tenant_created", "tenant_id", "created_at"),
        Index("ix_merge_decisions_candidate", "candidate_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("merge_candidates.id", ondelete="SET NULL"), nullable=True
    )
    decision_type: Mapped[MergeDecisionType] = mapped_column(
        enum_column(MergeDecisionType, 32), nullable=False
    )
    source: Mapped[MergeDecisionSource] = mapped_column(
        enum_column(MergeDecisionSource, 32), nullable=False
    )
    actor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExtractionRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "extraction_runs"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id",
            "input_hash",
            "schema_version",
            "prompt_version",
            "extractor_version",
            "model_name",
            name="uq_extraction_runs_ready_key",
        ),
        Index("ix_extraction_runs_tenant_status", "tenant_id", "status"),
        Index("ix_extraction_runs_document_version", "document_version_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[ExtractionRunStatus] = mapped_column(
        enum_column(ExtractionRunStatus, 32),
        nullable=False,
        default=ExtractionRunStatus.PENDING,
    )
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(100), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    manifest_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    manifest_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invocation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted_entity_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted_relation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted_claim_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_metrics: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)


class ExtractionInvocation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "extraction_invocations"
    __table_args__ = (
        UniqueConstraint(
            "extraction_run_id",
            "invocation_index",
            name="uq_extraction_invocations_run_index",
        ),
        Index("ix_extraction_invocations_run", "extraction_run_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    extraction_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invocation_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ExtractionInvocationStatus] = mapped_column(
        enum_column(ExtractionInvocationStatus, 32),
        nullable=False,
    )
    input_chunk_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    request_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    response_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class ExtractionArtifact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "extraction_artifacts"
    __table_args__ = (
        UniqueConstraint("extraction_run_id", name="uq_extraction_artifacts_run"),
        UniqueConstraint("tenant_id", "content_hash", name="uq_extraction_artifacts_hash"),
        Index("ix_extraction_artifacts_run", "extraction_run_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    extraction_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    object_uri: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


class EvidenceSpan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evidence_spans"
    __table_args__ = (
        UniqueConstraint("tenant_id", "stable_id", name="uq_evidence_spans_stable_id"),
        UniqueConstraint(
            "tenant_id",
            "document_version_id",
            "chunk_id",
            "start_offset",
            "end_offset",
            "span_hash",
            name="uq_evidence_spans_location",
        ),
        Index("ix_evidence_spans_run", "extraction_run_id"),
        Index("ix_evidence_spans_document_version", "document_version_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    extraction_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stable_id: Mapped[str] = mapped_column(String(100), nullable=False)
    chunk_id: Mapped[str] = mapped_column(String(100), nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    span_hash: Mapped[str] = mapped_column(String(128), nullable=False)


class ExtractedEntity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "extracted_entities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "stable_id", name="uq_extracted_entities_stable_id"),
        UniqueConstraint(
            "extraction_run_id", "local_id", name="uq_extracted_entities_run_local_id"
        ),
        Index("ix_extracted_entities_run", "extraction_run_id"),
        Index(
            "ix_extracted_entities_tenant_type_name",
            "tenant_id",
            "entity_type",
            "normalized_name",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    extraction_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stable_id: Mapped[str] = mapped_column(String(128), nullable=False)
    local_id: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(500), nullable=False)
    entity_type: Mapped[EntityType] = mapped_column(enum_column(EntityType, 32), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[StagedProposalStatus] = mapped_column(
        enum_column(StagedProposalStatus, 32),
        nullable=False,
        default=StagedProposalStatus.ACCEPTED,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ExtractedRelation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "extracted_relations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "stable_id", name="uq_extracted_relations_stable_id"),
        UniqueConstraint(
            "extraction_run_id", "local_id", name="uq_extracted_relations_run_local_id"
        ),
        Index("ix_extracted_relations_run", "extraction_run_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    extraction_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stable_id: Mapped[str] = mapped_column(String(128), nullable=False)
    local_id: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_extracted_entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("extracted_entities.id", ondelete="CASCADE"), nullable=False
    )
    predicate: Mapped[str] = mapped_column(String(200), nullable=False)
    object_extracted_entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("extracted_entities.id", ondelete="CASCADE"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[StagedProposalStatus] = mapped_column(
        enum_column(StagedProposalStatus, 32),
        nullable=False,
        default=StagedProposalStatus.ACCEPTED,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ExtractedClaim(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "extracted_claims"
    __table_args__ = (
        UniqueConstraint("tenant_id", "stable_id", name="uq_extracted_claims_stable_id"),
        UniqueConstraint(
            "extraction_run_id", "local_id", name="uq_extracted_claims_run_local_id"
        ),
        Index("ix_extracted_claims_run", "extraction_run_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    extraction_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stable_id: Mapped[str] = mapped_column(String(128), nullable=False)
    local_id: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_extracted_entity_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("extracted_entities.id", ondelete="CASCADE"), nullable=True
    )
    predicate: Mapped[str] = mapped_column(String(200), nullable=False)
    object_extracted_entity_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("extracted_entities.id", ondelete="CASCADE"), nullable=True
    )
    object_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    claim_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[StagedProposalStatus] = mapped_column(
        enum_column(StagedProposalStatus, 32),
        nullable=False,
        default=StagedProposalStatus.ACCEPTED,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ExtractedEntityEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "extracted_entity_evidence"
    __table_args__ = (
        UniqueConstraint(
            "extracted_entity_id",
            "evidence_span_id",
            name="uq_extracted_entity_evidence_pair",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    extracted_entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("extracted_entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evidence_span_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_spans.id", ondelete="CASCADE"), nullable=False, index=True
    )


class ExtractedRelationEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "extracted_relation_evidence"
    __table_args__ = (
        UniqueConstraint(
            "extracted_relation_id",
            "evidence_span_id",
            name="uq_extracted_relation_evidence_pair",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    extracted_relation_id: Mapped[UUID] = mapped_column(
        ForeignKey("extracted_relations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evidence_span_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_spans.id", ondelete="CASCADE"), nullable=False, index=True
    )


class ExtractedClaimEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "extracted_claim_evidence"
    __table_args__ = (
        UniqueConstraint(
            "extracted_claim_id",
            "evidence_span_id",
            name="uq_extracted_claim_evidence_pair",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    extracted_claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("extracted_claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evidence_span_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_spans.id", ondelete="CASCADE"), nullable=False, index=True
    )


class EntityResolutionCandidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "entity_resolution_candidates"
    __table_args__ = (
        Index("ix_entity_resolution_candidates_tenant_status", "tenant_id", "status"),
        Index("ix_entity_resolution_candidates_source", "source_extracted_entity_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_extracted_entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("extracted_entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_kind: Mapped[CandidateTargetKind] = mapped_column(
        enum_column(CandidateTargetKind, 32), nullable=False
    )
    target_canonical_entity_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("canonical_entities.id", ondelete="CASCADE"), nullable=True
    )
    target_extracted_entity_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("extracted_entities.id", ondelete="CASCADE"), nullable=True
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    features: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    outcome: Mapped[CandidateOutcome] = mapped_column(
        enum_column(CandidateOutcome, 32), nullable=False
    )
    status: Mapped[MergeCandidateStatus] = mapped_column(
        enum_column(MergeCandidateStatus, 32),
        nullable=False,
        default=MergeCandidateStatus.PENDING,
    )
