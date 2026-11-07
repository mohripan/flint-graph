"""Generation from the assistant always waits for the creator's press (ADR 0068).

Revision ID: 0051_generation_waits
Revises: 0050_narrative_music
"""

from alembic import op

revision = "0051_generation_waits"
down_revision = "0050_narrative_music"
branch_labels = None
depends_on = None

NAME = "ck_narrative_assistant_action_status"
TABLE = "narrative_assistant_actions"
OLD = "status IN ('offered','waiting','pending','started','blocked','finished','skipped')"
NEW = "status IN ('offered','pending','started','blocked','finished','skipped','declined')"


def upgrade() -> None:
    # What was set to start by itself under the old setting asks first, like everything else.
    op.execute(f"UPDATE {TABLE} SET status = 'offered' WHERE status IN ('waiting','pending')")
    op.drop_constraint(NAME, TABLE, type_="check")
    op.create_check_constraint(NAME, TABLE, NEW)


def downgrade() -> None:
    op.execute(f"UPDATE {TABLE} SET status = 'skipped' WHERE status = 'declined'")
    op.drop_constraint(NAME, TABLE, type_="check")
    op.create_check_constraint(NAME, TABLE, OLD)
