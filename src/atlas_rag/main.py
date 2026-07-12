from fastapi import FastAPI

from atlas_rag.api.errors import install_error_handlers
from atlas_rag.api.middleware import RequestContextMiddleware
from atlas_rag.api.router import api_router
from atlas_rag.config import get_settings
from atlas_rag.logging import configure_logging
from atlas_rag.observability.tracing import configure_tracing


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    
    app = FastAPI(
        title="AtlasRAG API",
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