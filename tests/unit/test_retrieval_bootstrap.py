from sqlalchemy import select

from flint_graph.application.services.retrieval_bootstrap import (
    bootstrap_retrieval_index,
)
from flint_graph.config import Settings
from flint_graph.domain.enums import RetrievalIndexScope, RetrievalIndexVersionStatus
from flint_graph.infrastructure.db.models import RetrievalIndexVersion, Tenant


async def test_bootstrap_creates_active_global_index_from_settings(db_session) -> None:
    settings = Settings(
        env="test",
        embedding_provider="deterministic",
        embedding_model="deterministic-test",
        embedding_dimensions=384,
    )

    version = await bootstrap_retrieval_index(db_session, settings=settings, tenant_id=None)

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

    first = await bootstrap_retrieval_index(db_session, settings=settings, tenant_id=None)
    second = await bootstrap_retrieval_index(db_session, settings=settings, tenant_id=None)

    assert second.id == first.id
    rows = list((await db_session.scalars(select(RetrievalIndexVersion))).all())
    assert len(rows) == 1


async def test_workspace_model_change_does_not_deprecate_global_or_foreign_indexes(db_session):
    settings = Settings(env="test")
    first_tenant, second_tenant = Tenant(name="First"), Tenant(name="Second")
    db_session.add_all([first_tenant, second_tenant])
    await db_session.flush()
    global_index = await bootstrap_retrieval_index(db_session, settings=settings, tenant_id=None)
    first = await bootstrap_retrieval_index(
        db_session, settings=settings, tenant_id=first_tenant.id
    )
    foreign = await bootstrap_retrieval_index(
        db_session, settings=settings, tenant_id=second_tenant.id
    )
    changed_settings = Settings(
        env="test", embedding_model="another-model", embedding_dimensions=64
    )
    changed = await bootstrap_retrieval_index(
        db_session, settings=changed_settings, tenant_id=first_tenant.id
    )
    assert changed.id != first.id
    assert changed.tenant_id == first_tenant.id
    assert first.status == RetrievalIndexVersionStatus.DEPRECATED
    assert global_index.status == foreign.status == RetrievalIndexVersionStatus.ACTIVE
