"""Document version cancelled status.

Revision ID: 0003_version_cancelled
Revises: 0002_outbox_messages
Create Date: 2026-07-13
"""

from collections.abc import Sequence

revision: str = "0003_version_cancelled"
down_revision: str | None = "0002_outbox_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # document_versions.status is a non-native string enum with no database CHECK constraint.
    # The existing VARCHAR length supports the new "cancelled" value.
    pass


def downgrade() -> None:
    pass
