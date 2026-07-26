import logging
import sys
from typing import Any
from uuid import UUID

import structlog

from flint_graph.config import Settings
from flint_graph.observability.redaction import RedactionProcessor


def configure_logging(settings: Settings) -> None:
    """Install structlog processors for the current process.

    Renderer choice follows the deployment: JSON for anything shipped to a log
    backend, console for a developer's terminal.
    """
    level = settings.log_level.upper()
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    renderer: Any
    if _use_console_renderer(settings):
        renderer = structlog.dev.ConsoleRenderer(colors=False)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            RedactionProcessor(allow_payloads=settings.log_payloads),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level, logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _use_console_renderer(settings: Settings) -> bool:
    if settings.log_renderer == "console":
        return True
    if settings.log_renderer == "json":
        return False
    return settings.env == "local"


def bind_log_context(**values: Any) -> None:
    """Bind correlation identifiers for every subsequent log line on this task.

    Values of ``None`` are dropped so callers can pass optional identifiers
    without branching, and UUIDs are stringified so the JSON renderer never has
    to guess.
    """
    bindable = {
        key: str(value) if isinstance(value, UUID) else value
        for key, value in values.items()
        if value is not None
    }
    if bindable:
        structlog.contextvars.bind_contextvars(**bindable)


def clear_log_context() -> None:
    structlog.contextvars.clear_contextvars()
