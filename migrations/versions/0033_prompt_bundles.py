"""Immutable prompt bundles and durable run references.
Revision ID: 0033_prompt_bundles
Revises: 0032_narrative_voice_models
"""

import sqlalchemy as sa
from alembic import op

revision = "0033_prompt_bundles"
down_revision = "0032_narrative_voice_models"
branch_labels = None
depends_on = None
TABLES = (
    "query_runs",
    "ingestion_jobs",
    "extraction_runs",
    "narrative_assistant_turns",
    "narrative_image_jobs",
)


def upgrade() -> None:
    op.create_table(
        "prompt_bundles",
        sa.Column("sha256", sa.String(64), primary_key=True),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("prompt_bundle_sha256", sa.String(64), nullable=True))
            batch.create_foreign_key(
                "fk_" + table + "_prompt_bundle",
                "prompt_bundles",
                ["prompt_bundle_sha256"],
                ["sha256"],
                ondelete="RESTRICT",
            )

    op.add_column("extraction_runs", sa.Column("prompt_identity", sa.JSON(), nullable=True))
    op.add_column("narrative_image_jobs", sa.Column("prompt_identity", sa.JSON(), nullable=True))
    with op.batch_alter_table("extraction_runs") as batch:
        batch.drop_constraint("uq_extraction_runs_ready_key", type_="unique")
        batch.create_unique_constraint(
            "uq_extraction_runs_ready_key",
            [
                "document_version_id",
                "input_hash",
                "schema_version",
                "prompt_version",
                "prompt_bundle_sha256",
                "extractor_version",
                "model_name",
            ],
        )


def downgrade() -> None:
    op.drop_column("narrative_image_jobs", "prompt_identity")
    op.drop_column("extraction_runs", "prompt_identity")
    with op.batch_alter_table("extraction_runs") as batch:
        batch.drop_constraint("uq_extraction_runs_ready_key", type_="unique")
        batch.create_unique_constraint(
            "uq_extraction_runs_ready_key",
            [
                "document_version_id",
                "input_hash",
                "schema_version",
                "prompt_version",
                "extractor_version",
                "model_name",
            ],
        )
    for table in reversed(TABLES):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint("fk_" + table + "_prompt_bundle", type_="foreignkey")
            batch.drop_column("prompt_bundle_sha256")
    op.drop_table("prompt_bundles")
