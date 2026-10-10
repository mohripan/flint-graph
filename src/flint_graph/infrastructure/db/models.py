from datetime import datetime
from enum import Enum as PyEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
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
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from flint_graph.domain.enums import (
    AliasSource,
    AuditAction,
    AuditOutcome,
    CandidateOutcome,
    CandidateTargetKind,
    ClaimStatus,
    DocumentArtifactType,
    DocumentIndexCoverageStatus,
    DocumentLifecycleEventType,
    DocumentProjectionCleanupStatus,
    DocumentVersionStatus,
    EntityStatus,
    EntityType,
    ExtractionInvocationStatus,
    ExtractionRunStatus,
    IndexBackfillJobStatus,
    IngestionJobStatus,
    MentionResolutionStatus,
    MergeCandidateBand,
    MergeCandidateStatus,
    MergeDecisionSource,
    MergeDecisionType,
    OutboxMessageStatus,
    ProviderUsageOperation,
    QueryRunStatus,
    RelationshipStatus,
    RetrievalIndexScope,
    RetrievalIndexVersionStatus,
    SourceType,
    StagedProposalStatus,
    StagedResolutionStatus,
    WorkspaceMembershipStatus,
    WorkspaceRole,
)
from flint_graph.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


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


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("oidc_issuer", "oidc_subject", name="uq_users_oidc_identity"),
        Index("ix_users_email", "email"),
    )

    oidc_issuer: Mapped[str] = mapped_column(String(500), nullable=False)
    oidc_subject: Mapped[str] = mapped_column(String(500), nullable=False)
    email: Mapped[str | None] = mapped_column(String(500), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    claims: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class WorkspaceMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_workspace_memberships_tenant_user"),
        Index("ix_workspace_memberships_user_status", "user_id", "status"),
        Index("ix_workspace_memberships_tenant_role", "tenant_id", "role"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[WorkspaceRole] = mapped_column(enum_column(WorkspaceRole, 32), nullable=False)
    status: Mapped[WorkspaceMembershipStatus] = mapped_column(
        enum_column(WorkspaceMembershipStatus, 32),
        nullable=False,
        default=WorkspaceMembershipStatus.ACTIVE,
    )


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
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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


class RetrievalIndexVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "retrieval_index_versions"
    __table_args__ = (
        CheckConstraint(
            "(scope = 'global' AND tenant_id IS NULL) OR "
            "(scope = 'tenant' AND tenant_id IS NOT NULL)",
            name="ck_retrieval_index_versions_scope_tenant",
        ),
        Index(
            "ix_retrieval_index_versions_scope_status",
            "scope",
            "tenant_id",
            "status",
        ),
        Index(
            "uq_retrieval_index_versions_active_global",
            "status",
            unique=True,
            postgresql_where=text("status = 'active' AND tenant_id IS NULL"),
            sqlite_where=text("status = 'active' AND tenant_id IS NULL"),
        ),
        Index(
            "uq_retrieval_index_versions_active_tenant",
            "tenant_id",
            "status",
            unique=True,
            postgresql_where=text("status = 'active' AND tenant_id IS NOT NULL"),
            sqlite_where=text("status = 'active' AND tenant_id IS NOT NULL"),
        ),
    )

    scope: Mapped[RetrievalIndexScope] = mapped_column(
        enum_column(RetrievalIndexScope, 32), nullable=False
    )
    tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    embedding_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    vector_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_config_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    chunking_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    chunking_config_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    lexical_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    neo4j_vector_index_name: Mapped[str] = mapped_column(String(200), nullable=False)
    neo4j_vector_property_name: Mapped[str] = mapped_column(String(200), nullable=False)
    opensearch_index_name: Mapped[str] = mapped_column(String(200), nullable=False)
    opensearch_alias_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[RetrievalIndexVersionStatus] = mapped_column(
        enum_column(RetrievalIndexVersionStatus, 32),
        nullable=False,
        default=RetrievalIndexVersionStatus.BUILDING,
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


class ChunkEmbedding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "retrieval_index_version_id",
            "document_version_id",
            "chunk_id",
            "chunk_hash",
            name="uq_chunk_embeddings_index_chunk_hash",
        ),
        Index("ix_chunk_embeddings_tenant_version", "tenant_id", "retrieval_index_version_id"),
        Index("ix_chunk_embeddings_document_version", "document_version_id"),
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
    retrieval_index_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("retrieval_index_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_id: Mapped[str] = mapped_column(String(100), nullable=False)
    chunk_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    vector_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    request_hash: Mapped[str] = mapped_column(String(128), nullable=False)


class DocumentIndexCoverage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_index_coverages"
    __table_args__ = (
        UniqueConstraint(
            "retrieval_index_version_id",
            "document_version_id",
            name="uq_document_index_coverages_version_document_version",
        ),
        Index("ix_document_index_coverages_tenant_status", "tenant_id", "status"),
        Index("ix_document_index_coverages_document_version", "document_version_id"),
        Index(
            "ix_document_index_coverages_index_version",
            "retrieval_index_version_id",
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
    retrieval_index_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("retrieval_index_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[DocumentIndexCoverageStatus] = mapped_column(
        enum_column(DocumentIndexCoverageStatus, 32),
        nullable=False,
        default=DocumentIndexCoverageStatus.RUNNING,
    )
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vector_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lexical_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class DocumentLifecycleEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_lifecycle_events"
    __table_args__ = (
        Index(
            "ix_document_lifecycle_events_tenant_document_created",
            "tenant_id",
            "document_id",
            "created_at",
        ),
        Index(
            "ix_document_lifecycle_events_document_version",
            "document_version_id",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[DocumentLifecycleEventType] = mapped_column(
        enum_column(DocumentLifecycleEventType, 64), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class DocumentProjectionCleanup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_projection_cleanups"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id",
            "retrieval_index_version_id",
            "stale_reason",
            name="uq_document_projection_cleanups_version_index_reason",
        ),
        Index(
            "ix_document_projection_cleanups_tenant_status",
            "tenant_id",
            "status",
        ),
        Index(
            "ix_document_projection_cleanups_document",
            "document_id",
            "created_at",
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
    retrieval_index_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("retrieval_index_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[DocumentProjectionCleanupStatus] = mapped_column(
        enum_column(DocumentProjectionCleanupStatus, 32),
        nullable=False,
        default=DocumentProjectionCleanupStatus.PENDING,
    )
    stale_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vector_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lexical_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class IndexBackfillJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "index_backfill_jobs"
    __table_args__ = (
        Index("ix_index_backfill_jobs_tenant_status", "tenant_id", "status"),
        Index("ix_index_backfill_jobs_version_status", "retrieval_index_version_id", "status"),
    )

    tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    retrieval_index_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("retrieval_index_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    document_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    status: Mapped[IndexBackfillJobStatus] = mapped_column(
        enum_column(IndexBackfillJobStatus, 32),
        nullable=False,
        default=IndexBackfillJobStatus.QUEUED,
    )
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    last_error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QueryRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "query_runs"
    __table_args__ = (
        Index("ix_query_runs_tenant_status_created", "tenant_id", "status", "created_at"),
        Index(
            "ix_query_runs_tenant_hash_created",
            "tenant_id",
            "normalized_query_hash",
            "created_at",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    retrieval_index_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("retrieval_index_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_query_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[QueryRunStatus] = mapped_column(
        enum_column(QueryRunStatus, 32),
        nullable=False,
        default=QueryRunStatus.QUEUED,
    )
    classification_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    retrieval_strategy: Mapped[str | None] = mapped_column(String(100), nullable=True)
    classification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    classification_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    abstained: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    abstain_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    supported_claim_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unsupported_claim_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    support_method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    answer_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Packing estimate produced before generation. Distinct from the provider-reported
    # token counts below, which are what the provider actually billed.
    context_token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Denormalized rollups of provider_usage_events for this run, so query history
    # renders from a single row instead of an aggregate per run.
    provider_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_cost_micros: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )

    events: Mapped[list["QueryRunEvent"]] = relationship(
        back_populates="query_run",
        cascade="all, delete-orphan",
        order_by="QueryRunEvent.sequence",
    )
    answer_claims: Mapped[list["QueryAnswerClaim"]] = relationship(
        back_populates="query_run",
        cascade="all, delete-orphan",
        order_by="QueryAnswerClaim.claim_index",
    )

    @property
    def query_diagnostics(self) -> dict[str, Any]:
        diagnostics = self.metadata_.get("diagnostics")
        return diagnostics if isinstance(diagnostics, dict) else {}

    @property
    def provider_usage_complete(self) -> bool | None:
        accounting = self.metadata_.get("usage_accounting")
        if not isinstance(accounting, dict):
            return None
        complete = accounting.get("complete")
        return complete if isinstance(complete, bool) else None


class QueryAnswerClaim(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "query_answer_claims"
    __table_args__ = (
        UniqueConstraint(
            "query_run_id",
            "claim_index",
            name="uq_query_answer_claims_run_index",
        ),
        Index("ix_query_answer_claims_run_index", "query_run_id", "claim_index"),
        Index("ix_query_answer_claims_tenant_status", "tenant_id", "support_status"),
    )

    query_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("query_runs.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    claim_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    citation_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    support_status: Mapped[str] = mapped_column(String(32), nullable=False)
    support_score: Mapped[float] = mapped_column(Float, nullable=False)
    support_reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    method: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    query_run: Mapped[QueryRun] = relationship(back_populates="answer_claims")


class QueryRunEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "query_run_events"
    __table_args__ = (
        UniqueConstraint(
            "query_run_id",
            "sequence",
            name="uq_query_run_events_run_sequence",
        ),
        Index("ix_query_run_events_run_sequence", "query_run_id", "sequence"),
        Index("ix_query_run_events_tenant_created", "tenant_id", "created_at"),
    )

    query_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("query_runs.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    query_run: Mapped[QueryRun] = relationship(back_populates="events")


class QueryRunLinkedEntity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "query_run_linked_entities"
    __table_args__ = (
        Index("ix_query_run_linked_entities_tenant_status", "tenant_id", "status"),
        Index("ix_query_run_linked_entities_run", "query_run_id"),
    )

    query_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("query_runs.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    canonical_entity_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("canonical_entities.id", ondelete="SET NULL"), nullable=True
    )
    mention_text: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    method: Mapped[str] = mapped_column(String(100), nullable=False)
    candidate_entity_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


class QueryRunCandidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "query_run_candidates"
    __table_args__ = (
        UniqueConstraint(
            "query_run_id",
            "dedupe_key",
            name="uq_query_run_candidates_run_dedupe",
        ),
        Index("ix_query_run_candidates_tenant_source", "tenant_id", "source"),
        Index("ix_query_run_candidates_run_rank", "query_run_id", "rank"),
    )

    query_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("query_runs.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    retrieval_index_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("retrieval_index_versions.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    candidate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ids: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(500), nullable=False)
    text_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_score: Mapped[float] = mapped_column(Float, nullable=False)
    normalized_score: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    fusion_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rerank_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rerank_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


class QueryContextPack(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "query_context_packs"
    __table_args__ = (
        UniqueConstraint(
            "query_run_id",
            "pack_version",
            name="uq_query_context_packs_run_version",
        ),
        Index("ix_query_context_packs_run_version", "query_run_id", "pack_version"),
    )

    query_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("query_runs.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    pack_id: Mapped[str] = mapped_column(String(200), nullable=False)
    pack_version: Mapped[int] = mapped_column(Integer, nullable=False)
    token_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_candidate_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    citation_map: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )

    records: Mapped[list["QueryContextPackRecord"]] = relationship(
        back_populates="context_pack",
        cascade="all, delete-orphan",
        order_by="QueryContextPackRecord.citation_id",
    )


class QueryContextPackRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "query_context_pack_records"
    __table_args__ = (
        UniqueConstraint(
            "query_context_pack_id",
            "citation_id",
            name="uq_query_context_pack_records_pack_citation",
        ),
        UniqueConstraint(
            "query_context_pack_id",
            "context_id",
            name="uq_query_context_pack_records_pack_context",
        ),
        Index("ix_query_context_pack_records_pack", "query_context_pack_id"),
    )

    query_context_pack_id: Mapped[UUID] = mapped_column(
        ForeignKey("query_context_packs.id", ondelete="CASCADE"), nullable=False
    )
    query_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("query_runs.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    context_id: Mapped[str] = mapped_column(String(200), nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(300), nullable=False)
    citation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_ids: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )

    context_pack: Mapped[QueryContextPack] = relationship(back_populates="records")


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
        Index(
            "ix_extracted_entities_tenant_resolution",
            "tenant_id",
            "resolution_status",
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
    resolution_status: Mapped[StagedResolutionStatus] = mapped_column(
        enum_column(StagedResolutionStatus, 32),
        nullable=False,
        default=StagedResolutionStatus.PENDING,
    )
    resolved_canonical_entity_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("canonical_entities.id", ondelete="SET NULL"), nullable=True
    )
    resolved_by_candidate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("entity_resolution_candidates.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


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


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only record of who performed a security-relevant action.

    Written in the same transaction as the mutation it describes, so an audited
    action cannot commit without its record. There is no update or delete path in
    application code; the table is a ledger, not state.

    ``tenant_id`` is nullable because workspace creation and user provisioning
    happen before a workspace membership exists.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_events_actor_created", "actor_user_id", "created_at"),
        Index("ix_audit_events_action_created", "action", "created_at"),
    )

    tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_issuer: Mapped[str | None] = mapped_column(String(500), nullable=True)
    actor_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    action: Mapped[AuditAction] = mapped_column(enum_column(AuditAction, 64), nullable=False)
    outcome: Mapped[AuditOutcome] = mapped_column(
        enum_column(AuditOutcome, 32), nullable=False, default=AuditOutcome.ALLOWED
    )
    resource_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    client_ip: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProviderUsageEvent(UUIDPrimaryKeyMixin, Base):
    """One model-provider call's consumption.

    Cost is stored in micros of ``currency`` and is nullable on purpose: when no
    pricing is configured for a provider/model, a null cost is honest and a
    fabricated one is not.
    """

    __tablename__ = "provider_usage_events"
    __table_args__ = (
        Index("ix_provider_usage_events_tenant_created", "tenant_id", "created_at"),
        Index(
            "ix_provider_usage_events_tenant_operation_created",
            "tenant_id",
            "operation",
            "created_at",
        ),
        Index("ix_provider_usage_events_query_run", "query_run_id"),
        CheckConstraint("input_tokens >= 0", name="ck_provider_usage_input_tokens"),
        CheckConstraint("output_tokens >= 0", name="ck_provider_usage_output_tokens"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    operation: Mapped[ProviderUsageOperation] = mapped_column(
        enum_column(ProviderUsageOperation, 32), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedded_item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_micros: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    query_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("query_runs.id", ondelete="CASCADE"), nullable=True
    )
    ingestion_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ingestion_jobs.id", ondelete="SET NULL"), nullable=True
    )
    document_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True
    )
    request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    workflow_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
