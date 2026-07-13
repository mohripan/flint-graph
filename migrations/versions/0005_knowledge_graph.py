"""Add knowledge graph and entity-resolution tables.

Revision ID: 0005_knowledge_graph
Revises: 0004_artifacts_chunks
Create Date: 2026-07-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_knowledge_graph"
down_revision: str | None = "0004_artifacts_chunks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

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
entity_status = sa.Enum(
    "active", "merged", "deprecated", name="entity_status", native_enum=False, length=32
)
alias_source = sa.Enum(
    "extraction", "merge", "manual", name="alias_source", native_enum=False, length=32
)
mention_resolution_status = sa.Enum(
    "pending",
    "resolved",
    "review",
    "rejected",
    name="mention_resolution_status",
    native_enum=False,
    length=32,
)
claim_status = sa.Enum(
    "pending", "linked", "rejected", name="claim_status", native_enum=False, length=32
)
relationship_status = sa.Enum(
    "active", "deprecated", name="relationship_status", native_enum=False, length=32
)
merge_candidate_band = sa.Enum(
    "auto", "review", "reject", name="merge_candidate_band", native_enum=False, length=32
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
merge_decision_type = sa.Enum(
    "attach",
    "merge",
    "no_merge",
    "split",
    name="merge_decision_type",
    native_enum=False,
    length=32,
)
merge_decision_source = sa.Enum(
    "auto", "human", name="merge_decision_source", native_enum=False, length=32
)


def _id_and_timestamps() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.Uuid(), nullable=False),
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


def upgrade() -> None:
    # pg_trgm powers the fuzzy candidate-generation lookups added in Milestone 04.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "canonical_entities",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", entity_type, nullable=False),
        sa.Column("canonical_name", sa.String(length=500), nullable=False),
        sa.Column("normalized_name", sa.String(length=500), nullable=False),
        sa.Column("status", entity_status, nullable=False),
        sa.Column("merged_into_id", sa.Uuid(), nullable=True),
        sa.Column("support_count", sa.Integer(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        *_id_and_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["merged_into_id"], ["canonical_entities.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_canonical_entities_tenant_id", "canonical_entities", ["tenant_id"])
    op.create_index(
        "ix_canonical_entities_tenant_type_name",
        "canonical_entities",
        ["tenant_id", "entity_type", "normalized_name"],
    )
    op.create_index(
        "ix_canonical_entities_tenant_status", "canonical_entities", ["tenant_id", "status"]
    )
    op.create_index(
        "ix_canonical_entities_normalized_name_trgm",
        "canonical_entities",
        ["normalized_name"],
        postgresql_using="gin",
        postgresql_ops={"normalized_name": "gin_trgm_ops"},
    )

    op.create_table(
        "entity_aliases",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_entity_id", sa.Uuid(), nullable=False),
        sa.Column("surface_form", sa.Text(), nullable=False),
        sa.Column("normalized_form", sa.String(length=500), nullable=False),
        sa.Column("source", alias_source, nullable=False),
        *_id_and_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["canonical_entity_id"], ["canonical_entities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "canonical_entity_id",
            "normalized_form",
            name="uq_entity_aliases_entity_form",
        ),
    )
    op.create_index("ix_entity_aliases_tenant_id", "entity_aliases", ["tenant_id"])
    op.create_index(
        "ix_entity_aliases_canonical_entity_id", "entity_aliases", ["canonical_entity_id"]
    )
    op.create_index(
        "ix_entity_aliases_tenant_form", "entity_aliases", ["tenant_id", "normalized_form"]
    )
    op.create_index(
        "ix_entity_aliases_normalized_form_trgm",
        "entity_aliases",
        ["normalized_form"],
        postgresql_using="gin",
        postgresql_ops={"normalized_form": "gin_trgm_ops"},
    )

    op.create_table(
        "entity_mentions",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("source_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("surface_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.String(length=500), nullable=False),
        sa.Column("entity_type", entity_type, nullable=False),
        sa.Column("chunk_ids", sa.JSON(), nullable=False),
        sa.Column("resolved_entity_id", sa.Uuid(), nullable=True),
        sa.Column("resolution_status", mention_resolution_status, nullable=False),
        sa.Column("prompt_hash", sa.String(length=128), nullable=True),
        sa.Column("response_hash", sa.String(length=128), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        *_id_and_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_artifact_id"], ["document_artifacts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["resolved_entity_id"], ["canonical_entities.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_entity_mentions_tenant_id", "entity_mentions", ["tenant_id"])
    op.create_index("ix_entity_mentions_document_id", "entity_mentions", ["document_id"])
    op.create_index(
        "ix_entity_mentions_document_version", "entity_mentions", ["document_version_id"]
    )
    op.create_index(
        "ix_entity_mentions_tenant_status", "entity_mentions", ["tenant_id", "resolution_status"]
    )
    op.create_index(
        "ix_entity_mentions_tenant_type_text",
        "entity_mentions",
        ["tenant_id", "entity_type", "normalized_text"],
    )
    op.create_index(
        "ix_entity_mentions_resolved_entity", "entity_mentions", ["resolved_entity_id"]
    )

    op.create_table(
        "claims",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("subject_mention_id", sa.Uuid(), nullable=False),
        sa.Column("predicate", sa.String(length=200), nullable=False),
        sa.Column("object_mention_id", sa.Uuid(), nullable=True),
        sa.Column("object_literal", sa.Text(), nullable=True),
        sa.Column("claim_text", sa.Text(), nullable=True),
        sa.Column("evidence_chunk_ids", sa.JSON(), nullable=False),
        sa.Column("status", claim_status, nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        *_id_and_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["subject_mention_id"], ["entity_mentions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["object_mention_id"], ["entity_mentions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_claims_tenant_id", "claims", ["tenant_id"])
    op.create_index("ix_claims_document_id", "claims", ["document_id"])
    op.create_index("ix_claims_document_version", "claims", ["tenant_id", "document_version_id"])
    op.create_index("ix_claims_subject_mention", "claims", ["subject_mention_id"])
    op.create_index("ix_claims_object_mention", "claims", ["object_mention_id"])
    op.create_index("ix_claims_tenant_status", "claims", ["tenant_id", "status"])

    op.create_table(
        "entity_relationships",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("subject_entity_id", sa.Uuid(), nullable=False),
        sa.Column("predicate", sa.String(length=200), nullable=False),
        sa.Column("object_entity_id", sa.Uuid(), nullable=False),
        sa.Column("support_count", sa.Integer(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("status", relationship_status, nullable=False),
        *_id_and_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["subject_entity_id"], ["canonical_entities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["object_entity_id"], ["canonical_entities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "subject_entity_id",
            "predicate",
            "object_entity_id",
            name="uq_entity_relationships_triple",
        ),
    )
    op.create_index("ix_entity_relationships_tenant_id", "entity_relationships", ["tenant_id"])
    op.create_index(
        "ix_entity_relationships_subject", "entity_relationships", ["subject_entity_id"]
    )
    op.create_index(
        "ix_entity_relationships_object", "entity_relationships", ["object_entity_id"]
    )

    op.create_table(
        "merge_candidates",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("mention_id", sa.Uuid(), nullable=True),
        sa.Column("source_entity_id", sa.Uuid(), nullable=True),
        sa.Column("target_entity_id", sa.Uuid(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("band", merge_candidate_band, nullable=False),
        sa.Column("status", merge_candidate_status, nullable=False),
        *_id_and_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["mention_id"], ["entity_mentions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_entity_id"], ["canonical_entities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_entity_id"], ["canonical_entities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_merge_candidates_tenant_id", "merge_candidates", ["tenant_id"])
    op.create_index(
        "ix_merge_candidates_tenant_status", "merge_candidates", ["tenant_id", "status"]
    )
    op.create_index("ix_merge_candidates_target", "merge_candidates", ["target_entity_id"])
    op.create_index("ix_merge_candidates_mention", "merge_candidates", ["mention_id"])

    op.create_table(
        "merge_decisions",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=True),
        sa.Column("decision_type", merge_decision_type, nullable=False),
        sa.Column("source", merge_decision_source, nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        *_id_and_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["merge_candidates.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_merge_decisions_tenant_id", "merge_decisions", ["tenant_id"])
    op.create_index(
        "ix_merge_decisions_tenant_created", "merge_decisions", ["tenant_id", "created_at"]
    )
    op.create_index("ix_merge_decisions_candidate", "merge_decisions", ["candidate_id"])


def downgrade() -> None:
    op.drop_table("merge_decisions")
    op.drop_table("merge_candidates")
    op.drop_table("entity_relationships")
    op.drop_table("claims")
    op.drop_table("entity_mentions")
    op.drop_table("entity_aliases")
    op.drop_table("canonical_entities")
    # The pg_trgm extension is intentionally left installed; it may be shared.
