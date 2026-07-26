from collections.abc import Awaitable, Callable
from time import monotonic
from uuid import uuid4

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from flint_graph.config import Settings
from flint_graph.logging import bind_log_context, clear_log_context
from flint_graph.observability import metrics


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
    """Correlation context, request logging fields, and API request metrics.

    The workspace selector is bound as a log field because almost every support
    question starts with "which workspace"; it is deliberately not a metric
    attribute, where it would be unbounded cardinality.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        request.state.request_id = request_id
        clear_log_context()
        bind_log_context(
            request_id=request_id,
            tenant_id=request.headers.get("X-Tenant-ID"),
            http_method=request.method,
            http_path=request.url.path,
        )
        started = monotonic()
        _in_flight.increment()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        finally:
            _in_flight.decrement()
            metrics.record_http_request(
                route=route_label(request),
                method=request.method,
                status_code=status_code,
                duration_ms=(monotonic() - started) * 1000,
            )
            clear_log_context()
        response.headers["X-Request-ID"] = request_id
        return response


class _InFlightCounter:
    """Tracks concurrent requests for the in-flight gauge.

    Starlette gives no hook for "requests currently executing", and a gauge that
    only rises is worse than none, so the count is kept here and published on
    every change.
    """

    def __init__(self) -> None:
        self._value = 0

    def increment(self) -> None:
        self._value += 1
        metrics.set_http_requests_in_flight(self._value)

    def decrement(self) -> None:
        self._value = max(0, self._value - 1)
        metrics.set_http_requests_in_flight(self._value)


_in_flight = _InFlightCounter()


def route_label(request: Request) -> str:
    """Return the templated route for metric attributes.

    Falls back to the literal path only for unmatched requests, which cannot
    contain identifiers a route template would otherwise hide.
    """
    route = request.scope.get("route")
    path_format = getattr(route, "path_format", None)
    if isinstance(path_format, str) and path_format:
        return path_format
    return "unmatched"


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
                metrics.record_request_size_rejection(route=limited_route_label(request))
                return problem_response(
                    status_code=413,
                    title="Payload too large",
                    detail="Request body exceeds the configured size limit.",
                    error_type="payload-too-large",
                    request=request,
                )
        return await call_next(request)


class FixedWindowRateLimitMiddleware(BaseHTTPMiddleware):
    # Public so the metric label helper can attribute rejections to a bounded set
    # of prefixes rather than to raw request paths.
    EXPENSIVE_PATHS = (
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
            metrics.record_rate_limit_rejection(route=limited_route_label(request))
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
        return any(request.url.path.startswith(path) for path in self.EXPENSIVE_PATHS)

    def _key(self, request: Request) -> str:
        user = (
            request.headers.get("X-Dev-User")
            or request.headers.get("Authorization")
            or (request.client.host if request.client else "unknown")
        )
        workspace = request.headers.get("X-Tenant-ID", "no-workspace")
        return f"{request.url.path}:{user}:{workspace}"


def limited_route_label(request: Request) -> str:
    """Bounded metric label for middleware that runs before routing.

    These middlewares see the raw path, which can embed identifiers, so
    rejections are attributed to the configured prefix they matched rather than
    to the literal URL.
    """
    path = request.url.path
    for prefix in FixedWindowRateLimitMiddleware.EXPENSIVE_PATHS:
        if path.startswith(prefix):
            return prefix
    return "other"


def _request_size_limit(request: Request, settings: Settings) -> int | None:
    if request.method not in {"POST", "PUT", "PATCH"}:
        return None
    if request.url.path == "/v1/documents/uploads":
        return settings.max_upload_bytes
    if request.url.path == "/v1/documents/from-url":
        return settings.max_url_intake_bytes
    return max(settings.max_upload_bytes or 0, settings.max_url_intake_bytes or 0) or None
