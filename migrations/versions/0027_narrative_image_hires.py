"""High-resolution character images: the upscale and the light repaint after it.

Revision ID: 0027_narrative_image_hires
Revises: 0026_narrative_image_expressions
"""

import sqlalchemy as sa
from alembic import op

revision = "0027_narrative_image_hires"
down_revision = "0026_narrative_image_expressions"
branch_labels = None
depends_on = None

HIRES = (
    "(hires_scale IS NULL AND hires_strength IS NULL) "
    "OR (purpose = 'character_portrait' AND hires_scale IN (1.5, 2.0) "
    "AND hires_strength BETWEEN 0.2 AND 0.6)"
)


def upgrade() -> None:
    op.add_column("narrative_image_jobs", sa.Column("hires_scale", sa.Float(), nullable=True))
    op.add_column("narrative_image_jobs", sa.Column("hires_strength", sa.Float(), nullable=True))
    op.create_check_constraint("ck_narrative_image_job_hires", "narrative_image_jobs", HIRES)


def downgrade() -> None:
    op.drop_constraint("ck_narrative_image_job_hires", "narrative_image_jobs", type_="check")
    op.drop_column("narrative_image_jobs", "hires_strength")
    op.drop_column("narrative_image_jobs", "hires_scale")
