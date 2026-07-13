from datetime import datetime
from enum import Enum as PyEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    DateTime,
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
    DocumentArtifactType,
    DocumentVersionStatus,
    IngestionJobStatus,
    OutboxMessageStatus,
    SourceType,
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
