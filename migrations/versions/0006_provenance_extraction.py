"""Add provenance-rich extraction proposal tables.

Revision ID: 0006_provenance_extraction
Revises: 0005_knowledge_graph
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_provenance_extraction"
down_revision: str | None = "0005_knowledge_graph"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

extraction_run_status = sa.Enum(
    "pending",
    "running",
    "ready",
    "failed",
    "cancelled",
    name="extraction_run_status",
    native_enum=False,
    length=32,
)
extraction_invocation_status = sa.Enum(
    "succeeded",
    "failed",
    name="extraction_invocation_status",
    native_enum=False,
    length=32,
)
staged_proposal_status = sa.Enum(
    "accepted",
    "rejected",
    name="staged_proposal_status",
    native_enum=False,
    length=32,
)
candidate_target_kind = sa.Enum(
    "canonical_entity",
    "extracted_entity",
    name="candidate_target_kind",
    native_enum=False,
    length=32,
)
candidate_outcome = sa.Enum(
    "auto",
    "review",
    "reject",
    name="candidate_outcome",
    native_enum=False,
    length=32,
)
entity_type = sa.Enum(
    "person",
    "organization",
    "place",
    "concept",
    "other",
    name="entity_type",
    native_enum=False,
    length=32,
)
merge_candidate_status = sa.Enum(
    "pending",
    "applied",
    "accepted",
    "rejected",
    name="merge_candidate_status",
    native_enum=False,
    length=32,
)


def _id_column() -> sa.Column:
    return sa.Column("id", sa.Uuid(), nullable=False)


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def _tenant_column() -> sa.Column:
    return sa.Column("tenant_id", sa.Uuid(), nullable=False)


def _document_columns() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
    )


def _tenant_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE")


def _document_fks() -> tuple[sa.ForeignKeyConstraint, sa.ForeignKeyConstraint]:
    return (
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="CASCADE"
        ),
    )


def upgrade() -> None:
    op.create_table(
        "extraction_runs",
        _tenant_column(),
        *_document_columns(),
        sa.Column("status", extraction_run_status, nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("extractor_version", sa.String(length=100), nullable=False),
        sa.Column("model_provider", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("input_hash", sa.String(length=128), nullable=False),
        sa.Column("manifest_uri", sa.Text(), nullable=True),
        sa.Column("manifest_hash", sa.String(length=128), nullable=True),
        sa.Column("input_chunk_count", sa.Integer(), nullable=False),
        sa.Column("invocation_count", sa.Integer(), nullable=False),
        sa.Column("accepted_entity_count", sa.Integer(), nullable=False),
        sa.Column("accepted_relation_count", sa.Integer(), nullable=False),
        sa.Column("accepted_claim_count", sa.Integer(), nullable=False),
        sa.Column("quality_metrics", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        _id_column(),
        *_timestamps(),
        _tenant_fk(),
        *_document_fks(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_version_id",
            "input_hash",
            "schema_version",
            "prompt_version",
            "extractor_version",
            "model_name",
            name="uq_extraction_runs_ready_key",
        ),
    )
    op.create_index(
        "ix_extraction_runs_tenant_status",
        "extraction_runs",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_extraction_runs_document_version",
        "extraction_runs",
        ["document_version_id"],
    )

    op.create_table(
        "extraction_invocations",
        _tenant_column(),
        sa.Column("extraction_run_id", sa.Uuid(), nullable=False),
        sa.Column("invocation_index", sa.Integer(), nullable=False),
        sa.Column("status", extraction_invocation_status, nullable=False),
        sa.Column("input_chunk_ids", sa.JSON(), nullable=False),
        sa.Column("request_hash", sa.String(length=128), nullable=False),
        sa.Column("response_hash", sa.String(length=128), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("input_char_count", sa.Integer(), nullable=False),
        sa.Column("output_char_count", sa.Integer(), nullable=False),
        sa.Column("prompt_token_count", sa.Integer(), nullable=True),
        sa.Column("completion_token_count", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        _id_column(),
        *_timestamps(),
        _tenant_fk(),
        sa.ForeignKeyConstraint(
            ["extraction_run_id"], ["extraction_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "extraction_run_id",
            "invocation_index",
            name="uq_extraction_invocations_run_index",
        ),
    )
    op.create_index(
        "ix_extraction_invocations_run",
        "extraction_invocations",
        ["extraction_run_id"],
    )

    op.create_table(
        "extraction_artifacts",
        _tenant_column(),
        sa.Column("extraction_run_id", sa.Uuid(), nullable=False),
        sa.Column("object_uri", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        _id_column(),
        *_timestamps(),
        _tenant_fk(),
        sa.ForeignKeyConstraint(
            ["extraction_run_id"], ["extraction_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("extraction_run_id", name="uq_extraction_artifacts_run"),
        sa.UniqueConstraint("tenant_id", "content_hash", name="uq_extraction_artifacts_hash"),
    )
    op.create_index(
        "ix_extraction_artifacts_run",
        "extraction_artifacts",
        ["extraction_run_id"],
    )

    op.create_table(
        "evidence_spans",
        _tenant_column(),
        *_document_columns(),
        sa.Column("extraction_run_id", sa.Uuid(), nullable=False),
        sa.Column("stable_id", sa.String(length=100), nullable=False),
        sa.Column("chunk_id", sa.String(length=100), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("span_hash", sa.String(length=128), nullable=False),
        _id_column(),
        *_timestamps(),
        _tenant_fk(),
        *_document_fks(),
        sa.ForeignKeyConstraint(
            ["extraction_run_id"], ["extraction_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "stable_id", name="uq_evidence_spans_stable_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "document_version_id",
            "chunk_id",
            "start_offset",
            "end_offset",
            "span_hash",
            name="uq_evidence_spans_location",
        ),
    )
    op.create_index("ix_evidence_spans_run", "evidence_spans", ["extraction_run_id"])
    op.create_index(
        "ix_evidence_spans_document_version",
        "evidence_spans",
        ["document_version_id"],
    )

    op.create_table(
        "extracted_entities",
        _tenant_column(),
        *_document_columns(),
        sa.Column("extraction_run_id", sa.Uuid(), nullable=False),
        sa.Column("stable_id", sa.String(length=128), nullable=False),
        sa.Column("local_id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("normalized_name", sa.String(length=500), nullable=False),
        sa.Column("entity_type", entity_type, nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("status", staged_proposal_status, nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        _id_column(),
        *_timestamps(),
        _tenant_fk(),
        *_document_fks(),
        sa.ForeignKeyConstraint(
            ["extraction_run_id"], ["extraction_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "stable_id", name="uq_extracted_entities_stable_id"
        ),
        sa.UniqueConstraint(
            "extraction_run_id",
            "local_id",
            name="uq_extracted_entities_run_local_id",
        ),
    )
    op.create_index("ix_extracted_entities_run", "extracted_entities", ["extraction_run_id"])
    op.create_index(
        "ix_extracted_entities_tenant_type_name",
        "extracted_entities",
        ["tenant_id", "entity_type", "normalized_name"],
    )

    op.create_table(
        "extracted_relations",
        _tenant_column(),
        *_document_columns(),
        sa.Column("extraction_run_id", sa.Uuid(), nullable=False),
        sa.Column("stable_id", sa.String(length=128), nullable=False),
        sa.Column("local_id", sa.String(length=100), nullable=False),
        sa.Column("subject_extracted_entity_id", sa.Uuid(), nullable=False),
        sa.Column("predicate", sa.String(length=200), nullable=False),
        sa.Column("object_extracted_entity_id", sa.Uuid(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("status", staged_proposal_status, nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        _id_column(),
        *_timestamps(),
        _tenant_fk(),
        *_document_fks(),
        sa.ForeignKeyConstraint(
            ["extraction_run_id"], ["extraction_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["subject_extracted_entity_id"], ["extracted_entities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["object_extracted_entity_id"], ["extracted_entities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "stable_id", name="uq_extracted_relations_stable_id"
        ),
        sa.UniqueConstraint(
            "extraction_run_id",
            "local_id",
            name="uq_extracted_relations_run_local_id",
        ),
    )
    op.create_index("ix_extracted_relations_run", "extracted_relations", ["extraction_run_id"])

    op.create_table(
        "extracted_claims",
        _tenant_column(),
        *_document_columns(),
        sa.Column("extraction_run_id", sa.Uuid(), nullable=False),
        sa.Column("stable_id", sa.String(length=128), nullable=False),
        sa.Column("local_id", sa.String(length=100), nullable=False),
        sa.Column("subject_extracted_entity_id", sa.Uuid(), nullable=True),
        sa.Column("predicate", sa.String(length=200), nullable=False),
        sa.Column("object_extracted_entity_id", sa.Uuid(), nullable=True),
        sa.Column("object_text", sa.Text(), nullable=True),
        sa.Column("claim_text", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("status", staged_proposal_status, nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        _id_column(),
        *_timestamps(),
        _tenant_fk(),
        *_document_fks(),
        sa.ForeignKeyConstraint(
            ["extraction_run_id"], ["extraction_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["subject_extracted_entity_id"], ["extracted_entities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["object_extracted_entity_id"], ["extracted_entities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "stable_id", name="uq_extracted_claims_stable_id"),
        sa.UniqueConstraint(
            "extraction_run_id",
            "local_id",
            name="uq_extracted_claims_run_local_id",
        ),
    )
    op.create_index("ix_extracted_claims_run", "extracted_claims", ["extraction_run_id"])

    op.create_table(
        "extracted_entity_evidence",
        _tenant_column(),
        sa.Column("extracted_entity_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_span_id", sa.Uuid(), nullable=False),
        _id_column(),
        *_timestamps(),
        _tenant_fk(),
        sa.ForeignKeyConstraint(
            ["extracted_entity_id"], ["extracted_entities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["evidence_span_id"], ["evidence_spans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "extracted_entity_id",
            "evidence_span_id",
            name="uq_extracted_entity_evidence_pair",
        ),
    )
    op.create_index(
        "ix_extracted_entity_evidence_tenant_id",
        "extracted_entity_evidence",
        ["tenant_id"],
    )
    op.create_index(
        "ix_extracted_entity_evidence_extracted_entity_id",
        "extracted_entity_evidence",
        ["extracted_entity_id"],
    )
    op.create_index(
        "ix_extracted_entity_evidence_evidence_span_id",
        "extracted_entity_evidence",
        ["evidence_span_id"],
    )

    op.create_table(
        "extracted_relation_evidence",
        _tenant_column(),
        sa.Column("extracted_relation_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_span_id", sa.Uuid(), nullable=False),
        _id_column(),
        *_timestamps(),
        _tenant_fk(),
        sa.ForeignKeyConstraint(
            ["extracted_relation_id"], ["extracted_relations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["evidence_span_id"], ["evidence_spans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "extracted_relation_id",
            "evidence_span_id",
            name="uq_extracted_relation_evidence_pair",
        ),
    )
    op.create_index(
        "ix_extracted_relation_evidence_tenant_id",
        "extracted_relation_evidence",
        ["tenant_id"],
    )
    op.create_index(
        "ix_extracted_relation_evidence_extracted_relation_id",
        "extracted_relation_evidence",
        ["extracted_relation_id"],
    )
    op.create_index(
        "ix_extracted_relation_evidence_evidence_span_id",
        "extracted_relation_evidence",
        ["evidence_span_id"],
    )

    op.create_table(
        "extracted_claim_evidence",
        _tenant_column(),
        sa.Column("extracted_claim_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_span_id", sa.Uuid(), nullable=False),
        _id_column(),
        *_timestamps(),
        _tenant_fk(),
        sa.ForeignKeyConstraint(
            ["extracted_claim_id"], ["extracted_claims.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["evidence_span_id"], ["evidence_spans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "extracted_claim_id",
            "evidence_span_id",
            name="uq_extracted_claim_evidence_pair",
        ),
    )
    op.create_index(
        "ix_extracted_claim_evidence_tenant_id",
        "extracted_claim_evidence",
        ["tenant_id"],
    )
    op.create_index(
        "ix_extracted_claim_evidence_extracted_claim_id",
        "extracted_claim_evidence",
        ["extracted_claim_id"],
    )
    op.create_index(
        "ix_extracted_claim_evidence_evidence_span_id",
        "extracted_claim_evidence",
        ["evidence_span_id"],
    )

    op.create_table(
        "entity_resolution_candidates",
        _tenant_column(),
        sa.Column("source_extracted_entity_id", sa.Uuid(), nullable=False),
        sa.Column("target_kind", candidate_target_kind, nullable=False),
        sa.Column("target_canonical_entity_id", sa.Uuid(), nullable=True),
        sa.Column("target_extracted_entity_id", sa.Uuid(), nullable=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("outcome", candidate_outcome, nullable=False),
        sa.Column("status", merge_candidate_status, nullable=False),
        _id_column(),
        *_timestamps(),
        _tenant_fk(),
        sa.ForeignKeyConstraint(
            ["source_extracted_entity_id"], ["extracted_entities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_canonical_entity_id"], ["canonical_entities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_extracted_entity_id"], ["extracted_entities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_entity_resolution_candidates_tenant_status",
        "entity_resolution_candidates",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_entity_resolution_candidates_source",
        "entity_resolution_candidates",
        ["source_extracted_entity_id"],
    )


def downgrade() -> None:
    op.drop_table("entity_resolution_candidates")
    op.drop_table("extracted_claim_evidence")
    op.drop_table("extracted_relation_evidence")
    op.drop_table("extracted_entity_evidence")
    op.drop_table("extracted_claims")
    op.drop_table("extracted_relations")
    op.drop_table("extracted_entities")
    op.drop_table("evidence_spans")
    op.drop_table("extraction_artifacts")
    op.drop_table("extraction_invocations")
    op.drop_table("extraction_runs")
