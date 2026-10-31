"""Character expressions repainted from a base sprite (ADR 0041).

Revision ID: 0026_narrative_image_expressions
Revises: 0025_narrative_image_cutout
"""

import sqlalchemy as sa
from alembic import op

revision = "0026_narrative_image_expressions"
down_revision = "0025_narrative_image_cutout"
branch_labels = None
depends_on = None

OLD_PURPOSE = (
    "(purpose = 'character_portrait' AND character_id IS NOT NULL) "
    "OR (purpose = 'background' AND character_id IS NULL)"
)
PURPOSE = (
    "(purpose IN ('character_portrait','character_expression') AND character_id IS NOT NULL) "
    "OR (purpose = 'background' AND character_id IS NULL)"
)
EXPRESSION = (
    "(purpose = 'character_expression') = (base_asset_id IS NOT NULL AND face_box IS NOT NULL "
    "AND strength IS NOT NULL AND expressions IS NOT NULL AND prompts IS NOT NULL)"
)


def upgrade() -> None:
    for name, column in (
        ("base_asset_id", sa.Uuid()),
        ("face_box", sa.JSON()),
        ("strength", sa.Float()),
        ("expressions", sa.JSON()),
        ("prompts", sa.JSON()),
    ):
        op.add_column("narrative_image_jobs", sa.Column(name, column, nullable=True))
    op.create_foreign_key(
        "fk_narrative_image_job_base_asset",
        "narrative_image_jobs",
        "narrative_assets",
        ["base_asset_id", "project_id", "tenant_id"],
        ["id", "project_id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("ck_narrative_image_job_purpose", "narrative_image_jobs", type_="check")
    op.create_check_constraint("ck_narrative_image_job_purpose", "narrative_image_jobs", PURPOSE)
    op.create_check_constraint(
        "ck_narrative_image_job_expression", "narrative_image_jobs", EXPRESSION
    )


def downgrade() -> None:
    op.drop_constraint("ck_narrative_image_job_expression", "narrative_image_jobs", type_="check")
    op.drop_constraint("ck_narrative_image_job_purpose", "narrative_image_jobs", type_="check")
    op.create_check_constraint(
        "ck_narrative_image_job_purpose", "narrative_image_jobs", OLD_PURPOSE
    )
    op.drop_constraint(
        "fk_narrative_image_job_base_asset", "narrative_image_jobs", type_="foreignkey"
    )
    for name in ("prompts", "expressions", "strength", "face_box", "base_asset_id"):
        op.drop_column("narrative_image_jobs", name)
