from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import httpx
from anthropic import AsyncAnthropic
from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.embeddings import EmbeddingModel
from flint_graph.application.query_orchestration import AnswerGenerator, SupportChecker
from flint_graph.application.services.authz import (
    AuthenticatedPrincipal,
    add_workspace_member,
    get_workspace_role,
    require_workspace_role,
    role_at_least,
    upsert_user_from_principal,
)
from flint_graph.config import Settings, get_settings
from flint_graph.domain.enums import WorkspaceRole
from flint_graph.domain.errors import NotFoundError, UnauthorizedError
from flint_graph.infrastructure.answer_generator_factory import (
    answer_generator_base_url,
    create_answer_generator,
    create_support_checker,
)
from flint_graph.infrastructure.db.models import Tenant, User
from flint_graph.infrastructure.db.session import get_session
from flint_graph.infrastructure.embedding_factory import (
    create_embedding_model,
    embedding_base_url,
)
from flint_graph.infrastructure.neo4j import Neo4jClient, create_neo4j_client
from flint_graph.infrastructure.object_store import ObjectStore, create_object_store
from flint_graph.infrastructure.oidc import OIDCTokenVerifier
from flint_graph.infrastructure.opensearch import OpenSearchClient, create_opensearch_client
from flint_graph.infrastructure.temporal import (
    TemporalIndexBackfillWorkflowStarter,
    connect_temporal,
)
from flint_graph.infrastructure.url_fetcher import HTTPURLFetcher, URLFetcher

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@dataclass(frozen=True, slots=True)
class CurrentUser:
    user: User
    principal: AuthenticatedPrincipal


def get_oidc_token_verifier(settings: SettingsDep) -> OIDCTokenVerifier:
    if settings.auth_mode == "dev":
        return OIDCTokenVerifier(
            issuer="dev",
            audience="dev",
            jwks_loader=lambda: {"keys": []},
        )
    if settings.oidc_issuer is None or settings.oidc_audience is None:
        raise UnauthorizedError("OIDC is not configured.")
    jwks_url = settings.oidc_jwks_url or (
        settings.oidc_issuer.rstrip("/") + "/protocol/openid-connect/certs"
    )

    async def load_jwks() -> dict[str, object]:
        async with httpx.AsyncClient() as client:
            response = await client.get(jwks_url, timeout=10.0)
            response.raise_for_status()
            body = response.json()
            return body if isinstance(body, dict) else {}

    return OIDCTokenVerifier(
        issuer=settings.oidc_issuer,
        audience=settings.oidc_audience,
        jwks_loader=load_jwks,
        email_claim=settings.oidc_email_claim,
        name_claim=settings.oidc_name_claim,
    )


OIDCTokenVerifierDep = Annotated[OIDCTokenVerifier, Depends(get_oidc_token_verifier)]


async def get_current_user(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    oidc_verifier: OIDCTokenVerifierDep,
) -> CurrentUser:
    if settings.auth_mode == "dev":
        principal = AuthenticatedPrincipal(
            issuer="dev",
            subject=request.headers.get("X-Dev-User", settings.dev_auth_subject),
            email=request.headers.get("X-Dev-Email", settings.dev_auth_email),
            display_name=request.headers.get("X-Dev-Name", settings.dev_auth_name),
            claims={"auth_mode": "dev"},
        )
        user = await upsert_user_from_principal(session, principal)
        return CurrentUser(user=user, principal=principal)

    auth = request.headers.get("Authorization")
    if auth is None or not auth.startswith("Bearer "):
        raise UnauthorizedError("A bearer access token is required.")
    principal = await oidc_verifier.verify(auth.removeprefix("Bearer ").strip())
    user = await upsert_user_from_principal(session, principal)
    return CurrentUser(user=user, principal=principal)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


async def get_tenant_id(
    session: SessionDep,
    settings: SettingsDep,
    current_user: CurrentUserDep,
    x_tenant_id: Annotated[UUID, Header(alias="X-Tenant-ID")],
) -> UUID:
    return await _authorize_tenant_id(
        session,
        settings=settings,
        current_user=current_user,
        tenant_id=x_tenant_id,
        minimum_role=WorkspaceRole.VIEWER,
    )


async def get_tenant_member_id(
    session: SessionDep,
    settings: SettingsDep,
    current_user: CurrentUserDep,
    x_tenant_id: Annotated[UUID, Header(alias="X-Tenant-ID")],
) -> UUID:
    return await _authorize_tenant_id(
        session,
        settings=settings,
        current_user=current_user,
        tenant_id=x_tenant_id,
        minimum_role=WorkspaceRole.MEMBER,
    )


async def get_tenant_admin_id(
    session: SessionDep,
    settings: SettingsDep,
    current_user: CurrentUserDep,
    x_tenant_id: Annotated[UUID, Header(alias="X-Tenant-ID")],
) -> UUID:
    return await _authorize_tenant_id(
        session,
        settings=settings,
        current_user=current_user,
        tenant_id=x_tenant_id,
        minimum_role=WorkspaceRole.ADMIN,
    )


async def _authorize_tenant_id(
    session: AsyncSession,
    *,
    settings: Settings,
    current_user: CurrentUser,
    tenant_id: UUID,
    minimum_role: WorkspaceRole,
) -> UUID:
    exists = await session.scalar(select(Tenant.id).where(Tenant.id == tenant_id))
    if exists is None:
        raise NotFoundError(f"Tenant '{tenant_id}' was not found.")
    role = await get_workspace_role(
        session,
        tenant_id=tenant_id,
        user_id=current_user.user.id,
    )
    if role is None and settings.auth_mode == "dev":
        await add_workspace_member(
            session,
            tenant_id=tenant_id,
            user_id=current_user.user.id,
            role=WorkspaceRole.OWNER,
        )
        role = WorkspaceRole.OWNER
    require_workspace_role(role, allowed=role_at_least(minimum_role))
    return tenant_id


TenantIdDep = Annotated[UUID, Depends(get_tenant_id)]
TenantMemberDep = Annotated[UUID, Depends(get_tenant_member_id)]
TenantAdminDep = Annotated[UUID, Depends(get_tenant_admin_id)]


def get_object_store(settings: SettingsDep) -> ObjectStore:
    return create_object_store(settings)


ObjectStoreDep = Annotated[ObjectStore, Depends(get_object_store)]


def get_url_fetcher(settings: SettingsDep) -> URLFetcher:
    return HTTPURLFetcher(
        timeout_seconds=settings.intake_url_timeout_seconds,
        max_bytes=settings.intake_max_source_bytes,
    )


URLFetcherDep = Annotated[URLFetcher, Depends(get_url_fetcher)]


async def get_neo4j_client(settings: SettingsDep) -> AsyncIterator[Neo4jClient]:
    client = create_neo4j_client(settings)
    try:
        yield client
    finally:
        await client.close()


Neo4jClientDep = Annotated[Neo4jClient, Depends(get_neo4j_client)]


async def get_opensearch_client(settings: SettingsDep) -> AsyncIterator[OpenSearchClient]:
    client = create_opensearch_client(settings)
    try:
        yield client
    finally:
        await client.close()


OpenSearchClientDep = Annotated[OpenSearchClient, Depends(get_opensearch_client)]


async def get_embedding_model(settings: SettingsDep) -> AsyncIterator[EmbeddingModel]:
    async with httpx.AsyncClient(base_url=embedding_base_url(settings)) as http_client:
        yield create_embedding_model(settings, http_client=http_client)


EmbeddingModelDep = Annotated[EmbeddingModel, Depends(get_embedding_model)]


async def get_answer_generator(settings: SettingsDep) -> AsyncIterator[AnswerGenerator]:
    if settings.query_answer_provider == "anthropic":
        async with AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.query_answer_timeout_seconds,
        ) as anthropic_client:
            yield create_answer_generator(settings, anthropic_client=anthropic_client)
        return
    async with httpx.AsyncClient(base_url=answer_generator_base_url(settings)) as http_client:
        yield create_answer_generator(settings, http_client=http_client)


AnswerGeneratorDep = Annotated[AnswerGenerator, Depends(get_answer_generator)]


async def get_support_checker(settings: SettingsDep) -> AsyncIterator[SupportChecker]:
    if settings.query_support_provider == "anthropic":
        async with AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.query_answer_timeout_seconds,
        ) as anthropic_client:
            yield create_support_checker(settings, anthropic_client=anthropic_client)
        return
    if settings.query_support_provider == "ollama":
        async with httpx.AsyncClient(base_url=answer_generator_base_url(settings)) as http_client:
            yield create_support_checker(settings, http_client=http_client)
        return
    yield create_support_checker(settings)


SupportCheckerDep = Annotated[SupportChecker, Depends(get_support_checker)]


async def get_index_backfill_workflow_starter(
    settings: SettingsDep,
) -> TemporalIndexBackfillWorkflowStarter:
    client = await connect_temporal(settings)
    return TemporalIndexBackfillWorkflowStarter(
        client,
        task_queue=settings.temporal_task_queue,
    )


IndexBackfillWorkflowStarterDep = Annotated[
    TemporalIndexBackfillWorkflowStarter,
    Depends(get_index_backfill_workflow_starter),
]
