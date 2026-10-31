"""Content-addressed generic prompt manifests; tenant inputs never belong here."""

from typing import Any

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from flint_graph.infrastructure.db.base import Base, TimestampMixin


class PromptBundleRecord(TimestampMixin, Base):
    __tablename__ = "prompt_bundles"
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class PromptBundleReference:
    prompt_bundle_sha256: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("prompt_bundles.sha256", ondelete="RESTRICT"), nullable=True
    )
