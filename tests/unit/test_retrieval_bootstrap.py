from sqlalchemy import select

from flint_graph.application.services.retrieval_bootstrap import (
    bootstrap_retrieval_index,
)
from flint_graph.config import Settings
from flint_graph.domain.enums import RetrievalIndexScope, RetrievalIndexVersionStatus
from flint_graph.infrastructure.db.models import RetrievalIndexVersion


async def test_bootstrap_creates_active_global_index_from_settings(db_session) -> None:
    settings = Settings(
        env="test",
        embedding_provider="deterministic",
        embedding_model="deterministic-test",
        embedding_dimensions=384,
    )

    version = await bootstrap_retrieval_index(db_session, settings=settings)

    assert version.scope == RetrievalIndexScope.GLOBAL
    assert version.tenant_id is None
    assert version.status == RetrievalIndexVersionStatus.ACTIVE
    assert version.embedding_provider == "deterministic"
    assert version.embedding_model == "deterministic-test"
    assert version.vector_dimension == 384


async def test_bootstrap_returns_existing_compatible_active_index(db_session) -> None:
    settings = Settings(
        env="test",
        embedding_provider="deterministic",
        embedding_model="deterministic-test",
        embedding_dimensions=384,
    )

    first = await bootstrap_retrieval_index(db_session, settings=settings)
    second = await bootstrap_retrieval_index(db_session, settings=settings)

    assert second.id == first.id
    rows = list((await db_session.scalars(select(RetrievalIndexVersion))).all())
    assert len(rows) == 1
