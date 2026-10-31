"""Event CGs drawn from approved images of one or two characters (ADR 0041 slice C).

Revision ID: 0030_narrative_scene_art
Revises: 0029_narrative_voice
"""

import sqlalchemy as sa
from alembic import op

revision = "0030_narrative_scene_art"
down_revision = "0029_narrative_voice"
branch_labels = None
depends_on = None

OLD_PURPOSE = (
    "(purpose IN ('character_portrait','character_expression') AND character_id IS NOT NULL) "
    "OR (purpose = 'background' AND character_id IS NULL)"
)
PURPOSE = (
    "(purpose IN ('character_portrait','character_expression','scene_art') "
    "AND character_id IS NOT NULL) OR (purpose = 'background' AND character_id IS NULL)"
)
SCENE = (
    "(purpose = 'scene_art') = (reference_assets IS NOT NULL AND ip_adapter_scale IS NOT NULL) "
    "AND (ip_adapter_model IS NULL OR purpose = 'scene_art') "
    "AND (status <> 'completed' OR purpose <> 'scene_art' OR ip_adapter_model IS NOT NULL)"
)


def upgrade() -> None:
    op.add_column("narrative_image_jobs", sa.Column("reference_assets", sa.JSON(), nullable=True))
    op.add_column("narrative_image_jobs", sa.Column("ip_adapter_scale", sa.Float(), nullable=True))
    op.add_column(
        "narrative_image_jobs", sa.Column("ip_adapter_model", sa.String(200), nullable=True)
    )
    op.drop_constraint("ck_narrative_image_job_purpose", "narrative_image_jobs", type_="check")
    op.create_check_constraint("ck_narrative_image_job_purpose", "narrative_image_jobs", PURPOSE)
    op.create_check_constraint("ck_narrative_image_job_scene", "narrative_image_jobs", SCENE)


def downgrade() -> None:
    op.drop_constraint("ck_narrative_image_job_scene", "narrative_image_jobs", type_="check")
    op.drop_constraint("ck_narrative_image_job_purpose", "narrative_image_jobs", type_="check")
    op.create_check_constraint(
        "ck_narrative_image_job_purpose", "narrative_image_jobs", OLD_PURPOSE
    )
    for name in ("ip_adapter_model", "ip_adapter_scale", "reference_assets"):
        op.drop_column("narrative_image_jobs", name)
