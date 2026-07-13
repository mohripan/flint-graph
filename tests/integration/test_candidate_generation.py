import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atlas_rag.application.services.candidate_generation import generate_candidates
from atlas_rag.domain.enums import AliasSource, EntityStatus, EntityType
from atlas_rag.infrastructure.db.models import (
    CanonicalEntity,
    EntityAlias,
    Tenant,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("ATLAS_PG_INTEGRATION"),
    reason="Set ATLAS_PG_INTEGRATION=1 with a running Postgres (pg_trgm) to run this test.",
)

PG_URL = os.getenv(
    "ATLAS_PG_TEST_URL", "postgresql+asyncpg://atlas:atlas@localhost:55432/atlas"
)


@pytest_asyncio.fixture
async def pg_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(PG_URL, poolclass=None)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


async def _seed_tenant(session: AsyncSession) -> tuple[Tenant, CanonicalEntity]:
    tenant = Tenant(name=f"cand-gen-{uuid4()}")
    session.add(tenant)
    await session.flush()

    acme = CanonicalEntity(
        tenant_id=tenant.id,
        entity_type=EntityType.ORGANIZATION,
        canonical_name="Acme Corporation",
        normalized_name="acme corporation",
        status=EntityStatus.ACTIVE,
    )
    globex = CanonicalEntity(
        tenant_id=tenant.id,
        entity_type=EntityType.ORGANIZATION,
        canonical_name="Globex Industries",
        normalized_name="globex industries",
        status=EntityStatus.ACTIVE,
    )
    deprecated = CanonicalEntity(
        tenant_id=tenant.id,
        entity_type=EntityType.ORGANIZATION,
        canonical_name="Zeta Corp",
        normalized_name="zeta corp",
        status=EntityStatus.DEPRECATED,
    )
    session.add_all([acme, globex, deprecated])
    await session.flush()
    session.add(
        EntityAlias(
            tenant_id=tenant.id,
            canonical_entity_id=acme.id,
            surface_form="Acme Corp",
            normalized_form="acme corp",
            source=AliasSource.EXTRACTION,
        )
    )
    await session.commit()
    return tenant, deprecated


async def test_candidate_generation_blocks_by_alias_fuzzy_type_and_status(
    pg_session: AsyncSession,
) -> None:
    tenant, deprecated = await _seed_tenant(pg_session)
    try:
        # Alias-exact match surfaces the entity that owns the alias.
        by_alias = await generate_candidates(
            pg_session,
            tenant_id=tenant.id,
            normalized_text="acme corp",
            entity_type=EntityType.ORGANIZATION,
            trigram_threshold=0.3,
            limit=20,
        )
        assert any(c.normalized_name == "acme corporation" for c in by_alias)

        # Fuzzy (typo) match via pg_trgm similarity on the canonical name.
        by_fuzzy = await generate_candidates(
            pg_session,
            tenant_id=tenant.id,
            normalized_text="acme corporatn",
            entity_type=EntityType.ORGANIZATION,
            trigram_threshold=0.3,
            limit=20,
        )
        assert any(c.normalized_name == "acme corporation" for c in by_fuzzy)

        # Type constraint: no person entity matches an organization name.
        by_type = await generate_candidates(
            pg_session,
            tenant_id=tenant.id,
            normalized_text="acme corporation",
            entity_type=EntityType.PERSON,
            trigram_threshold=0.3,
            limit=20,
        )
        assert by_type == []

        # Deprecated entities are excluded even on an exact-name query.
        results = await generate_candidates(
            pg_session,
            tenant_id=tenant.id,
            normalized_text="zeta corp",
            entity_type=EntityType.ORGANIZATION,
            trigram_threshold=0.3,
            limit=20,
        )
        assert deprecated.id not in {candidate.entity_id for candidate in results}
    finally:
        await pg_session.execute(delete(Tenant).where(Tenant.id == tenant.id))
        await pg_session.commit()
