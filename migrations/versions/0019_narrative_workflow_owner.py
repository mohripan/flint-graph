"""Bind narrative activity attempts to an accepted Temporal workflow run."""

import sqlalchemy as sa
from alembic import op

revision = "0019_narrative_workflow_owner"
down_revision = "0018_narrative_releases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("narrative_release_jobs", sa.Column("workflow_run_id", sa.Uuid(), nullable=True))
    op.add_column(
        "narrative_release_jobs", sa.Column("activity_attempt", sa.Integer(), nullable=True)
    )
    op.create_check_constraint(
        "ck_narrative_release_workflow_owner",
        "narrative_release_jobs",
        "(workflow_run_id IS NULL AND activity_attempt IS NULL) OR "
        "(workflow_run_id IS NOT NULL AND activity_attempt IS NOT NULL "
        "AND activity_attempt >= 0)",
    )
    op.create_index(
        "ix_narrative_release_run_status", "narrative_release_jobs", ["status", "workflow_run_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_narrative_release_run_status", table_name="narrative_release_jobs")
    op.drop_constraint(
        "ck_narrative_release_workflow_owner", "narrative_release_jobs", type_="check"
    )
    op.drop_column("narrative_release_jobs", "activity_attempt")
    op.drop_column("narrative_release_jobs", "workflow_run_id")
