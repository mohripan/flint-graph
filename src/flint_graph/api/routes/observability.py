"""Operational read surfaces: audit ledger, usage accounting, and metrics scrape.

Audit and usage are workspace-scoped and admin-only. The metrics endpoint is not
part of the tenant API at all: it is an operator surface, disabled by default,
and token-gated when enabled.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from flint_graph.api.dependencies import (
    SessionDep,
    SettingsDep,
    TenantAdminDep,
)
from flint_graph.api.schemas import (
    AuditEventResponse,
    UsageRollupResponse,
    UsageSummaryResponse,
)
from flint_graph.application.services.audit import list_audit_events
from flint_graph.application.services.usage import summarize_usage
from flint_graph.domain.enums import AuditAction, AuditOutcome
from flint_graph.domain.errors import UnauthorizedError
from flint_graph.observability import metrics

router = APIRouter(prefix="/v1", tags=["observability"])


@router.get("/audit-events", response_model=list[AuditEventResponse])
async def list_audit_events_endpoint(
    tenant_id: TenantAdminDep,
    session: SessionDep,
    action: AuditAction | None = None,
    outcome: AuditOutcome | None = None,
    actor_user_id: UUID | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AuditEventResponse]:
    events = await list_audit_events(
        session,
        tenant_id=tenant_id,
        action=action,
        outcome=outcome,
        actor_user_id=actor_user_id,
        created_after=created_after,
        created_before=created_before,
        limit=limit,
    )
    return [AuditEventResponse.model_validate(event) for event in events]


@router.get("/usage", response_model=UsageSummaryResponse)
async def get_usage_endpoint(
    tenant_id: TenantAdminDep,
    session: SessionDep,
    settings: SettingsDep,
    group_by: Literal["day", "operation", "model"] = "day",
    created_after: datetime | None = None,
    created_before: datetime | None = None,
) -> UsageSummaryResponse:
    summary = await summarize_usage(
        session,
        tenant_id=tenant_id,
        group_by=group_by,
        created_after=created_after,
        created_before=created_before,
        currency=settings.usage_currency,
    )
    return UsageSummaryResponse(
        currency=summary.currency,
        group_by=summary.group_by,
        rows=[UsageRollupResponse.model_validate(row) for row in summary.rows],
        totals=UsageRollupResponse.model_validate(summary.totals),
    )


async def scrape_metrics(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    """Prometheus scrape endpoint.

    Registered by ``create_app`` only when ``metrics_enabled`` is set, so a
    deployment with metrics off has no such route at all. When a token is
    configured — mandatory in staging/production, see ``Settings`` validation — it
    is required.
    """
    if settings.metrics_token:
        expected = f"Bearer {settings.metrics_token}"
        if authorization != expected:
            raise UnauthorizedError("A valid metrics token is required.")
    payload, content_type = metrics.render_prometheus_metrics()
    return Response(content=payload, media_type=content_type)
