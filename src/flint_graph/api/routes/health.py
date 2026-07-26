from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from flint_graph.api.dependencies import ReadinessCheckerDep, SessionDep
from flint_graph.application.services.health_probes import report_payload

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def liveness() -> dict[str, str]:
    """Process liveness only.

    Deliberately dependency-free: a database outage must not make the platform
    restart every replica.
    """
    return {"status": "ok"}


@router.get("/ready")
async def readiness(
    request: Request,
    session: SessionDep,
    checker: ReadinessCheckerDep,
) -> Any:
    """Dependency readiness.

    Returns 503 with ``application/problem+json`` naming the failed dependencies
    when a required one is unavailable, and 200 with ``status: degraded`` when only
    optional dependencies are unhealthy.
    """
    report = await checker.check(session)
    payload = report_payload(report)
    if report.http_status_code == 200:
        return payload

    failed = ", ".join(dependency.name for dependency in report.failed_required())
    return JSONResponse(
        status_code=report.http_status_code,
        media_type="application/problem+json",
        content={
            "type": "urn:flint-graph:error:dependency-unavailable",
            "title": "Dependencies unavailable",
            "status": report.http_status_code,
            "detail": f"Required dependencies are unavailable: {failed}.",
            "instance": str(request.url.path),
            "request_id": getattr(request.state, "request_id", None),
            **payload,
        },
    )
