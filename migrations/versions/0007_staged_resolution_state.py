"""Add staged entity resolution state.

Revision ID: 0007_staged_resolution_state
Revises: 0006_provenance_extraction
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_staged_resolution_state"
down_revision: str | None = "0006_provenance_extraction"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

staged_resolution_status = sa.Enum(
    "pending",
    "resolved",
    "review",
    "rejected",
    name="staged_resolution_status",
    native_enum=False,
    length=32,
)


def upgrade() -> None:
    op.add_column(
        "extracted_entities",
        sa.Column(
            "resolution_status",
            staged_resolution_status,
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column(
        "extracted_entities",
        sa.Column("resolved_canonical_entity_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "extracted_entities",
        sa.Column("resolved_by_candidate_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "extracted_entities",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("extracted_entities", "resolution_status", server_default=None)
    op.create_foreign_key(
        "fk_extracted_entities_resolved_canonical_entity",
        "extracted_entities",
        "canonical_entities",
        ["resolved_canonical_entity_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_extracted_entities_resolved_by_candidate",
        "extracted_entities",
        "entity_resolution_candidates",
        ["resolved_by_candidate_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_extracted_entities_tenant_resolution",
        "extracted_entities",
        ["tenant_id", "resolution_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_extracted_entities_tenant_resolution", table_name="extracted_entities")
    op.drop_constraint(
        "fk_extracted_entities_resolved_by_candidate",
        "extracted_entities",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_extracted_entities_resolved_canonical_entity",
        "extracted_entities",
        type_="foreignkey",
    )
    op.drop_column("extracted_entities", "resolved_at")
    op.drop_column("extracted_entities", "resolved_by_candidate_id")
    op.drop_column("extracted_entities", "resolved_canonical_entity_id")
    op.drop_column("extracted_entities", "resolution_status")
