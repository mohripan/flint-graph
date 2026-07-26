from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from flint_graph.api.errors import install_error_handlers
from flint_graph.api.middleware import (
    FixedWindowRateLimitMiddleware,
    RequestContextMiddleware,
    RequestSizeLimitMiddleware,
)
from flint_graph.api.router import api_router
from flint_graph.api.routes.observability import scrape_metrics
from flint_graph.config import Settings, get_settings
from flint_graph.observability.runtime import API_ROLE, configure_observability


def create_app(settings_override: Settings | None = None) -> FastAPI:
    settings = settings_override or get_settings()

    app = FastAPI(
        title="FlintGraph API",
        version=settings.service_version,
        docs_url="/docs" if settings.env != "production" else None,
        redoc_url=None,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware, settings=settings)
    app.add_middleware(FixedWindowRateLimitMiddleware, settings=settings)
    if settings.require_tls:
        app.add_middleware(HTTPSRedirectMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-Tenant-ID",
            "X-Dev-User",
            "X-Dev-Email",
            "X-Dev-Name",
            "X-Request-ID",
        ],
    )
    install_error_handlers(app)
    app.include_router(api_router)
    if settings.metrics_enabled:
        # Registered only when enabled, so a deployment with metrics off does not
        # expose the route at all. It is intentionally outside /v1 and out of the
        # OpenAPI schema: this is an operator surface, not tenant API.
        app.add_api_route(
            settings.metrics_path,
            scrape_metrics,
            methods=["GET"],
            include_in_schema=False,
        )
    configure_observability(settings, role=API_ROLE, app=app)
    return app


app = create_app()
