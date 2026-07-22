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
from flint_graph.config import Settings, get_settings
from flint_graph.logging import configure_logging
from flint_graph.observability.tracing import configure_tracing


def create_app(settings_override: Settings | None = None) -> FastAPI:
    settings = settings_override or get_settings()
    configure_logging(settings.log_level)

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
    configure_tracing(app, settings)
    return app


app = create_app()
