"""Whether the GPU machine is up: not tied to a workspace, and holds nothing private."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from flint_graph.infrastructure.db.base import Base


class NarrativeGpuStatus(Base):
    """One row per GPU worker, kept fresh while it runs, and one for the controller (#197)."""

    __tablename__ = "narrative_gpu_status"
    __table_args__ = (
        CheckConstraint(
            "state IN ('ready','stopped','starting','stopping','unavailable')",
            name="ck_narrative_gpu_status_state",
        ),
    )

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    state: Mapped[str] = mapped_column(String(16))
    detail: Mapped[str | None] = mapped_column(String(40), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
