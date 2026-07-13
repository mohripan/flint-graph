from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from atlas_rag.api.dependencies import get_neo4j_client
from atlas_rag.domain.enums import (
    AliasSource,
    EntityStatus,
    EntityType,
    MentionResolutionStatus,
    MergeCandidateBand,
    MergeCandidateStatus,
    SourceType,
)
from atlas_rag.infrastructure.db.base import Base
from atlas_rag.infrastructure.db.models import (
    CanonicalEntity,
    Document,
    DocumentVersion,
    EntityAlias,
    EntityMention,
    MergeCandidate,
    Tenant,
)
from atlas_rag.infrastructure.db.session import get_session
from atlas_rag.main import app


class CapturingNeo4jClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        self.calls.append((query, parameters or {}))
        return []

    async def close(self) -> None:
        return None


@pytest_asyncio.fixture
async def graph_env() -> AsyncIterator[
    tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession], CapturingNeo4jClient]
]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    fake = CapturingNeo4jClient()
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_neo4j_client] = lambda: fake
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, session_factory, fake
    app.dependency_overrides.clear()
    await engine.dispose()


async def _tenant(session: AsyncSession, name: str) -> Tenant:
    tenant = Tenant(name=name)
    session.add(tenant)
    await session.flush()
    return tenant


async def _entity(
    session: AsyncSession, tenant: Tenant, name: str, normalized: str, *, support: int = 1
) -> CanonicalEntity:
    entity = CanonicalEntity(
        tenant_id=tenant.id,
        entity_type=EntityType.ORGANIZATION,
        canonical_name=name,
        normalized_name=normalized,
        status=EntityStatus.ACTIVE,
        support_count=support,
    )
    session.add(entity)
    await session.flush()
    session.add(
        EntityAlias(
            tenant_id=tenant.id,
            canonical_entity_id=entity.id,
            surface_form=name,
            normalized_form=normalized,
            source=AliasSource.EXTRACTION,
        )
    )
    return entity


async def _version(session: AsyncSession, tenant: Tenant, external_id: str) -> DocumentVersion:
    document = Document(
        tenant_id=tenant.id,
        title=external_id,
        external_id=external_id,
        source_type=SourceType.UPLOAD,
        next_version_number=1,
    )
    session.add(document)
    await session.flush()
    version = DocumentVersion(document_id=document.id, version_number=1)
    session.add(version)
    await session.flush()
    return version


async def _review_mention(
    session: AsyncSession, tenant: Tenant, version: DocumentVersion, surface: str, normalized: str
) -> EntityMention:
    mention = EntityMention(
        tenant_id=tenant.id,
        document_id=version.document_id,
        document_version_id=version.id,
        surface_text=surface,
        normalized_text=normalized,
        entity_type=EntityType.ORGANIZATION,
        resolution_status=MentionResolutionStatus.REVIEW,
    )
    session.add(mention)
    await session.flush()
    return mention


def _headers(tenant_id: UUID) -> dict[str, str]:
    return {"X-Tenant-ID": str(tenant_id)}


async def test_list_and_get_entity_with_tenant_isolation(
    graph_env: tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession], CapturingNeo4jClient],
) -> None:
    client, session_factory, _ = graph_env
    async with session_factory() as session:
        tenant = await _tenant(session, "tenant-a")
        other = await _tenant(session, "tenant-b")
        entity = await _entity(session, tenant, "Acme Corporation", "acme corporation", support=3)
        await session.commit()
        entity_id = entity.id
        other_id = other.id

    listing = await client.get("/v1/entities", headers=_headers(tenant.id))
    assert listing.status_code == 200
    assert [e["canonical_name"] for e in listing.json()] == ["Acme Corporation"]

    detail = await client.get(f"/v1/entities/{entity_id}", headers=_headers(tenant.id))
    assert detail.status_code == 200
    body = detail.json()
    assert body["support_count"] == 3
    assert len(body["aliases"]) == 1

    # A foreign tenant cannot see the entity.
    foreign = await client.get(f"/v1/entities/{entity_id}", headers=_headers(other_id))
    assert foreign.status_code == 404


async def test_review_accept_attaches_to_target_and_projects(
    graph_env: tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession], CapturingNeo4jClient],
) -> None:
    client, session_factory, fake = graph_env
    async with session_factory() as session:
        tenant = await _tenant(session, "tenant-a")
        target = await _entity(session, tenant, "Acme Corp", "acme corp", support=1)
        version = await _version(session, tenant, "doc-1")
        mention = await _review_mention(
            session, tenant, version, "Acme Corporation", "acme corporation"
        )
        candidate = MergeCandidate(
            tenant_id=tenant.id,
            mention_id=mention.id,
            target_entity_id=target.id,
            score=0.7,
            features={},
            band=MergeCandidateBand.REVIEW,
            status=MergeCandidateStatus.PENDING,
        )
        session.add(candidate)
        await session.commit()
        tenant_id, target_id, mention_id, candidate_id = (
            tenant.id,
            target.id,
            mention.id,
            candidate.id,
        )

    reviews = await client.get("/v1/merge-reviews", headers=_headers(tenant_id))
    assert reviews.status_code == 200
    assert len(reviews.json()) == 1

    response = await client.post(
        f"/v1/merge-reviews/{candidate_id}/decision",
        headers=_headers(tenant_id),
        json={"decision": "accept", "reason": "same company"},
    )
    assert response.status_code == 200

    async with session_factory() as session:
        refreshed = await session.get(EntityMention, mention_id)
        assert refreshed is not None
        assert refreshed.resolution_status == MentionResolutionStatus.RESOLVED
        assert refreshed.resolved_entity_id == target_id
        resolved_target = await session.get(CanonicalEntity, target_id)
        assert resolved_target is not None
        assert resolved_target.support_count == 2

    # Queue is now empty and the projection ran.
    assert (await client.get("/v1/merge-reviews", headers=_headers(tenant_id))).json() == []
    assert fake.calls


async def test_review_reject_creates_distinct_entity(
    graph_env: tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession], CapturingNeo4jClient],
) -> None:
    client, session_factory, _ = graph_env
    async with session_factory() as session:
        tenant = await _tenant(session, "tenant-a")
        target = await _entity(session, tenant, "Acme Corp", "acme corp")
        version = await _version(session, tenant, "doc-1")
        mention = await _review_mention(session, tenant, version, "Acme Ltd", "acme ltd")
        candidate = MergeCandidate(
            tenant_id=tenant.id,
            mention_id=mention.id,
            target_entity_id=target.id,
            score=0.65,
            features={},
            band=MergeCandidateBand.REVIEW,
            status=MergeCandidateStatus.PENDING,
        )
        session.add(candidate)
        await session.commit()
        tenant_id, target_id, mention_id, candidate_id = (
            tenant.id,
            target.id,
            mention.id,
            candidate.id,
        )

    response = await client.post(
        f"/v1/merge-reviews/{candidate_id}/decision",
        headers=_headers(tenant_id),
        json={"decision": "reject", "reason": "different company"},
    )
    assert response.status_code == 200

    async with session_factory() as session:
        refreshed = await session.get(EntityMention, mention_id)
        assert refreshed is not None
        assert refreshed.resolution_status == MentionResolutionStatus.RESOLVED
        assert refreshed.resolved_entity_id is not None
        assert refreshed.resolved_entity_id != target_id


async def test_merge_then_unmerge_via_api_with_audit(
    graph_env: tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession], CapturingNeo4jClient],
) -> None:
    client, session_factory, _ = graph_env
    async with session_factory() as session:
        tenant = await _tenant(session, "tenant-a")
        source = await _entity(session, tenant, "Acme Inc", "acme inc", support=2)
        target = await _entity(session, tenant, "Acme Corporation", "acme corporation", support=3)
        version = await _version(session, tenant, "doc-1")
        mention = EntityMention(
            tenant_id=tenant.id,
            document_id=version.document_id,
            document_version_id=version.id,
            surface_text="Acme Inc",
            normalized_text="acme inc",
            entity_type=EntityType.ORGANIZATION,
            resolution_status=MentionResolutionStatus.RESOLVED,
            resolved_entity_id=source.id,
        )
        session.add(mention)
        await session.commit()
        tenant_id, source_id, target_id, mention_id = (
            tenant.id,
            source.id,
            target.id,
            mention.id,
        )

    merge = await client.post(
        f"/v1/entities/{source_id}/merge",
        headers=_headers(tenant_id),
        json={"target_entity_id": str(target_id), "reason": "duplicate"},
    )
    assert merge.status_code == 200

    detail = await client.get(f"/v1/entities/{source_id}", headers=_headers(tenant_id))
    assert detail.json()["status"] == "merged"
    assert detail.json()["merged_into_id"] == str(target_id)
    async with session_factory() as session:
        moved = await session.get(EntityMention, mention_id)
        assert moved is not None and moved.resolved_entity_id == target_id
        merged_target = await session.get(CanonicalEntity, target_id)
        assert merged_target is not None and merged_target.support_count == 5

    unmerge = await client.post(
        f"/v1/entities/{source_id}/unmerge",
        headers=_headers(tenant_id),
        json={"reason": "was not a duplicate"},
    )
    assert unmerge.status_code == 200

    detail = await client.get(f"/v1/entities/{source_id}", headers=_headers(tenant_id))
    assert detail.json()["status"] == "active"
    assert detail.json()["merged_into_id"] is None
    async with session_factory() as session:
        restored = await session.get(EntityMention, mention_id)
        assert restored is not None and restored.resolved_entity_id == source_id
        restored_target = await session.get(CanonicalEntity, target_id)
        assert restored_target is not None and restored_target.support_count == 3

    audit = await client.get("/v1/merge-decisions", headers=_headers(tenant_id))
    decision_types = {row["decision_type"] for row in audit.json()}
    assert {"merge", "split"} <= decision_types


async def test_merge_foreign_entity_returns_404(
    graph_env: tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession], CapturingNeo4jClient],
) -> None:
    client, session_factory, _ = graph_env
    async with session_factory() as session:
        tenant = await _tenant(session, "tenant-a")
        other = await _tenant(session, "tenant-b")
        source = await _entity(session, tenant, "Acme Inc", "acme inc")
        target = await _entity(session, tenant, "Acme Corporation", "acme corporation")
        await session.commit()
        source_id, target_id, other_id = source.id, target.id, other.id

    response = await client.post(
        f"/v1/entities/{source_id}/merge",
        headers=_headers(other_id),
        json={"target_entity_id": str(target_id)},
    )
    assert response.status_code == 404
