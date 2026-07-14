from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.domain.enums import RetrievalIndexScope, RetrievalIndexVersionStatus
from atlas_rag.domain.errors import ConflictError, NotFoundError
from atlas_rag.infrastructure.db.models import RetrievalIndexVersion


@dataclass(frozen=True, slots=True)
class RetrievalIndexVersionSpec:
    embedding_provider: str
    embedding_model: str
    vector_dimension: int
    embedding_config_hash: str
    chunking_schema_version: str
    chunking_config_hash: str
    lexical_schema_version: str
    neo4j_vector_index_name: str
    neo4j_vector_property_name: str
    opensearch_index_name: str
    opensearch_alias_name: str
    metadata: dict[str, object] = field(default_factory=dict)


async def create_retrieval_index_version(
    session: AsyncSession,
    *,
    scope: RetrievalIndexScope,
    spec: RetrievalIndexVersionSpec,
    tenant_id: UUID | None = None,
) -> RetrievalIndexVersion:
    _validate_scope(scope=scope, tenant_id=tenant_id)
    version = RetrievalIndexVersion(
        scope=scope,
        tenant_id=tenant_id,
        embedding_provider=spec.embedding_provider,
        embedding_model=spec.embedding_model,
        vector_dimension=spec.vector_dimension,
        embedding_config_hash=spec.embedding_config_hash,
        chunking_schema_version=spec.chunking_schema_version,
        chunking_config_hash=spec.chunking_config_hash,
        lexical_schema_version=spec.lexical_schema_version,
        neo4j_vector_index_name=spec.neo4j_vector_index_name,
        neo4j_vector_property_name=spec.neo4j_vector_property_name,
        opensearch_index_name=spec.opensearch_index_name,
        opensearch_alias_name=spec.opensearch_alias_name,
        status=RetrievalIndexVersionStatus.BUILDING,
        metadata_=dict(spec.metadata),
    )
    session.add(version)
    await session.flush()
    return version


async def activate_retrieval_index_version(
    session: AsyncSession,
    *,
    version_id: UUID,
) -> RetrievalIndexVersion:
    version = await _load_version_for_update(session, version_id)
    if version.status == RetrievalIndexVersionStatus.ACTIVE:
        return version
    if version.status != RetrievalIndexVersionStatus.BUILDING:
        raise ConflictError(
            f"Cannot activate retrieval index version '{version_id}' from "
            f"'{version.status}' status."
        )

    now = datetime.now(UTC)
    active_versions = list(
        (
            await session.execute(
                select(RetrievalIndexVersion)
                .where(
                    RetrievalIndexVersion.scope == version.scope,
                    RetrievalIndexVersion.tenant_id.is_(version.tenant_id)
                    if version.tenant_id is None
                    else RetrievalIndexVersion.tenant_id == version.tenant_id,
                    RetrievalIndexVersion.status == RetrievalIndexVersionStatus.ACTIVE,
                    RetrievalIndexVersion.id != version.id,
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for active_version in active_versions:
        active_version.status = RetrievalIndexVersionStatus.DEPRECATED
        active_version.deprecated_at = now
    if active_versions:
        await session.flush()

    version.status = RetrievalIndexVersionStatus.ACTIVE
    version.activated_at = now
    version.error_code = None
    version.error_message = None
    await session.flush()
    return version


async def deprecate_retrieval_index_version(
    session: AsyncSession,
    *,
    version_id: UUID,
) -> RetrievalIndexVersion:
    version = await _load_version_for_update(session, version_id)
    if version.status == RetrievalIndexVersionStatus.DEPRECATED:
        return version
    if version.status == RetrievalIndexVersionStatus.FAILED:
        raise ConflictError(
            f"Cannot deprecate retrieval index version '{version_id}' from failed status."
        )
    version.status = RetrievalIndexVersionStatus.DEPRECATED
    version.deprecated_at = datetime.now(UTC)
    await session.flush()
    return version


async def fail_retrieval_index_version(
    session: AsyncSession,
    *,
    version_id: UUID,
    error_code: str,
    error_message: str,
) -> RetrievalIndexVersion:
    version = await _load_version_for_update(session, version_id)
    if version.status == RetrievalIndexVersionStatus.ACTIVE:
        raise ConflictError(
            f"Cannot fail active retrieval index version '{version_id}'. Deprecate it first."
        )
    if version.status == RetrievalIndexVersionStatus.FAILED:
        return version

    version.status = RetrievalIndexVersionStatus.FAILED
    version.failed_at = datetime.now(UTC)
    version.error_code = error_code
    version.error_message = error_message
    await session.flush()
    return version


async def _load_version_for_update(
    session: AsyncSession,
    version_id: UUID,
) -> RetrievalIndexVersion:
    version = await session.scalar(
        select(RetrievalIndexVersion)
        .where(RetrievalIndexVersion.id == version_id)
        .with_for_update()
    )
    if version is None:
        raise NotFoundError(f"Retrieval index version '{version_id}' was not found.")
    return version


def _validate_scope(*, scope: RetrievalIndexScope, tenant_id: UUID | None) -> None:
    if scope == RetrievalIndexScope.GLOBAL and tenant_id is not None:
        raise ConflictError("tenant_id must be empty for global retrieval index versions.")
    if scope == RetrievalIndexScope.TENANT and tenant_id is None:
        raise ConflictError("tenant_id is required for tenant retrieval index versions.")
