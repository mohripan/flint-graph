from fastapi import FastAPI

from flint_graph.api.errors import install_error_handlers
from flint_graph.api.middleware import RequestContextMiddleware
from flint_graph.api.router import api_router
from flint_graph.config import get_settings
from flint_graph.logging import configure_logging
from flint_graph.observability.tracing import configure_tracing


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    
    app = FastAPI(
        title="FlintGraph API",
        version=settings.service_version,
        docs_url="/docs" if settings.env != "production" else None,
        redoc_url=None,
    )
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    app.include_router(api_router)
    configure_tracing(app, settings)
    return app


app = create_app()