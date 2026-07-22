from collections.abc import Awaitable, Callable
from time import monotonic
from uuid import uuid4

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from flint_graph.config import Settings


def problem_response(
    *,
    status_code: int,
    title: str,
    detail: str,
    error_type: str,
    request: Request,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "type": f"urn:flint-graph:error:{error_type}",
            "title": title,
            "status": status_code,
            "detail": detail,
            "instance": str(request.url.path),
            "request_id": getattr(request.state, "request_id", None),
        },
        media_type="application/problem+json",
    )


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        request.state.request_id = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers["X-Request-ID"] = request_id
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        limit = _request_size_limit(request, self._settings)
        content_length = request.headers.get("content-length")
        if limit is not None and content_length is not None:
            try:
                size = int(content_length)
            except ValueError:
                size = 0
            if size > limit:
                return problem_response(
                    status_code=413,
                    title="Payload too large",
                    detail="Request body exceeds the configured size limit.",
                    error_type="payload-too-large",
                    request=request,
                )
        return await call_next(request)


class FixedWindowRateLimitMiddleware(BaseHTTPMiddleware):
    _EXPENSIVE_PATHS = (
        "/v1/documents/uploads",
        "/v1/documents/from-url",
        "/v1/query-runs",
        "/v1/search/lexical",
        "/v1/search/vector",
        "/v1/retrieval-index/bootstrap",
        "/v1/retrieval-index/backfill-active",
        "/v1/index-backfills",
    )

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings
        self._buckets: dict[str, tuple[float, int]] = {}

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not self._should_limit(request):
            return await call_next(request)
        key = self._key(request)
        now = monotonic()
        window_start, count = self._buckets.get(key, (now, 0))
        if now - window_start >= self._settings.rate_limit_window_seconds:
            window_start = now
            count = 0
        count += 1
        self._buckets[key] = (window_start, count)
        if count > self._settings.rate_limit_requests:
            response = problem_response(
                status_code=429,
                title="Too many requests",
                detail="Rate limit exceeded for this user and workspace.",
                error_type="too-many-requests",
                request=request,
            )
            response.headers["Retry-After"] = str(
                max(1, int(self._settings.rate_limit_window_seconds - (now - window_start)))
            )
            return response
        return await call_next(request)

    def _should_limit(self, request: Request) -> bool:
        if not self._settings.rate_limit_enabled:
            return False
        if request.method not in {"GET", "POST"}:
            return False
        return any(request.url.path.startswith(path) for path in self._EXPENSIVE_PATHS)

    def _key(self, request: Request) -> str:
        user = (
            request.headers.get("X-Dev-User")
            or request.headers.get("Authorization")
            or (request.client.host if request.client else "unknown")
        )
        workspace = request.headers.get("X-Tenant-ID", "no-workspace")
        return f"{request.url.path}:{user}:{workspace}"


def _request_size_limit(request: Request, settings: Settings) -> int | None:
    if request.method not in {"POST", "PUT", "PATCH"}:
        return None
    if request.url.path == "/v1/documents/uploads":
        return settings.max_upload_bytes
    if request.url.path == "/v1/documents/from-url":
        return settings.max_url_intake_bytes
    return max(settings.max_upload_bytes or 0, settings.max_url_intake_bytes or 0) or None
