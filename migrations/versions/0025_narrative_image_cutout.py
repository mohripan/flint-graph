"""Transparent character sprites: the request flag and the segmenter that cut them out.

Revision ID: 0025_narrative_image_cutout
Revises: 0024_narrative_asset_library
"""

import sqlalchemy as sa
from alembic import op

revision = "0025_narrative_image_cutout"
down_revision = "0024_narrative_asset_library"
branch_labels = None
depends_on = None

TRANSPARENT = "NOT transparent OR (purpose = 'character_portrait' AND framing = 'full_body')"
CUTOUT = (
    "((cutout_model IS NULL AND cutout_sha256 IS NULL) "
    "OR (transparent AND cutout_model IS NOT NULL AND cutout_sha256 IS NOT NULL)) "
    "AND (status <> 'completed' OR NOT transparent OR cutout_model IS NOT NULL)"
)


def upgrade() -> None:
    op.add_column(
        "narrative_image_jobs",
        sa.Column("transparent", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("narrative_image_jobs", "transparent", server_default=None)
    op.add_column(
        "narrative_image_jobs", sa.Column("cutout_model", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "narrative_image_jobs", sa.Column("cutout_sha256", sa.String(length=64), nullable=True)
    )
    op.create_check_constraint(
        "ck_narrative_image_job_transparent", "narrative_image_jobs", TRANSPARENT
    )
    op.create_check_constraint("ck_narrative_image_job_cutout", "narrative_image_jobs", CUTOUT)


def downgrade() -> None:
    op.drop_constraint("ck_narrative_image_job_cutout", "narrative_image_jobs", type_="check")
    op.drop_constraint("ck_narrative_image_job_transparent", "narrative_image_jobs", type_="check")
    for column in ("cutout_sha256", "cutout_model", "transparent"):
        op.drop_column("narrative_image_jobs", column)
