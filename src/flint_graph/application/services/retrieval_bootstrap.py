from __future__ import annotations

import json
import re
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.retrieval_index_versions import (
    RetrievalIndexVersionSpec,
    activate_retrieval_index_version,
    create_retrieval_index_version,
)
from flint_graph.config import Settings
from flint_graph.domain.enums import RetrievalIndexScope, RetrievalIndexVersionStatus
from flint_graph.domain.errors import ConflictError, NotFoundError
from flint_graph.infrastructure.db.models import RetrievalIndexVersion, Tenant

_CHUNKING_SCHEMA_VERSION = "1"
_LEXICAL_SCHEMA_VERSION = "1"


async def bootstrap_retrieval_index(
    session: AsyncSession,
    *,
    settings: Settings,
    tenant_id: UUID | None,
    preserve_active: bool = False,
) -> RetrievalIndexVersion:
    # None is an explicit internal operator choice, never the workspace API default.
    scope = RetrievalIndexScope.GLOBAL if tenant_id is None else RetrievalIndexScope.TENANT
    if tenant_id is not None:
        # Serialize same-workspace bootstraps even when no index exists yet.
        tenant = await session.scalar(
            select(Tenant).where(Tenant.id == tenant_id).with_for_update()
        )
        if tenant is None:
            raise NotFoundError(f"Workspace '{tenant_id}' was not found.")
    scope_filter = (
        RetrievalIndexVersion.tenant_id.is_(None)
        if tenant_id is None else RetrievalIndexVersion.tenant_id == tenant_id
    )
    spec = retrieval_index_spec_from_settings(settings)
    active = await session.scalar(
        select(RetrievalIndexVersion).where(
            RetrievalIndexVersion.scope == scope,
            scope_filter,
            RetrievalIndexVersion.status == RetrievalIndexVersionStatus.ACTIVE,
        )
    )
    if active is not None and _matches_spec(active, spec):
        return active
    if active is not None and preserve_active:
        raise ConflictError("Incompatible active index; guarded bootstrap will not replace it.")

    building = await session.scalar(
        select(RetrievalIndexVersion).where(
            RetrievalIndexVersion.scope == scope,
            scope_filter,
            RetrievalIndexVersion.status == RetrievalIndexVersionStatus.BUILDING,
            RetrievalIndexVersion.embedding_config_hash == spec.embedding_config_hash,
            RetrievalIndexVersion.chunking_config_hash == spec.chunking_config_hash,
            RetrievalIndexVersion.lexical_schema_version == spec.lexical_schema_version,
        )
    )
    version = building
    if version is None:
        version = await create_retrieval_index_version(
            session,
            scope=scope,
            tenant_id=tenant_id,
            spec=spec,
        )
    activated = await activate_retrieval_index_version(session, version_id=version.id)
    await session.refresh(activated)
    return activated


def retrieval_index_spec_from_settings(settings: Settings) -> RetrievalIndexVersionSpec:
    provider = settings.embedding_provider or "deterministic"
    model = settings.embedding_model
    dimensions = settings.embedding_dimensions
    embedding_payload = {
        "provider": provider,
        "model": model,
        "dimensions": dimensions,
    }
    chunking_payload = {
        "schema_version": _CHUNKING_SCHEMA_VERSION,
        "max_chunk_chars": settings.chunking_max_chunk_chars,
        "overlap_chars": settings.chunking_overlap_chars,
    }
    suffix = _slug(f"{provider}-{model}-{dimensions}")
    return RetrievalIndexVersionSpec(
        embedding_provider=provider,
        embedding_model=model,
        vector_dimension=dimensions,
        embedding_config_hash=_hash_payload(embedding_payload),
        chunking_schema_version=_CHUNKING_SCHEMA_VERSION,
        chunking_config_hash=_hash_payload(chunking_payload),
        lexical_schema_version=_LEXICAL_SCHEMA_VERSION,
        neo4j_vector_index_name=f"flint_graph_chunks_{suffix}",
        neo4j_vector_property_name=f"embedding_{dimensions}",
        opensearch_index_name=f"flint_graph_chunks_{suffix}",
        opensearch_alias_name="flint_graph_chunks_active",
        metadata={
            "bootstrap": True,
            "embedding": embedding_payload,
            "chunking": chunking_payload,
        },
    )


def _matches_spec(version: RetrievalIndexVersion, spec: RetrievalIndexVersionSpec) -> bool:
    return (
        version.embedding_provider == spec.embedding_provider
        and version.embedding_model == spec.embedding_model
        and version.vector_dimension == spec.vector_dimension
        and version.embedding_config_hash == spec.embedding_config_hash
        and version.chunking_schema_version == spec.chunking_schema_version
        and version.chunking_config_hash == spec.chunking_config_hash
        and version.lexical_schema_version == spec.lexical_schema_version
    )


def _hash_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return slug[:80] or "default"
