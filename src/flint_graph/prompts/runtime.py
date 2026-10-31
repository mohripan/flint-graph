"""Process lifecycle for optional prompt management; availability never gates reads."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.datastructures import State
from starlette.types import ASGIApp, Receive, Scope, Send

from flint_graph.config import Settings, get_settings
from flint_graph.prompts.catalog import PromptError
from flint_graph.prompts.langfuse import LangfusePromptSource, LangfuseReader, PromptReader
from flint_graph.prompts.source import (
    DEFAULT_LOCK,
    LockedPromptSource,
    configure_source,
    current_snapshot,
    use_snapshot,
)


@asynccontextmanager
async def prompt_runtime(
    settings: Settings, *, reader: PromptReader | None = None
) -> AsyncIterator[LockedPromptSource | LangfusePromptSource]:
    lock = LockedPromptSource.load(
        Path(settings.prompt_lock_path) if settings.prompt_lock_path else DEFAULT_LOCK
    )
    if settings.prompt_lock_path:
        required = {entry.name for entry in LockedPromptSource.load().snapshot().entries}
        if not required.issubset({entry.name for entry in lock.snapshot().entries}):
            raise PromptError("incomplete_catalog")
    source: LockedPromptSource | LangfusePromptSource = lock
    if settings.prompt_source == "langfuse":
        if not settings.langfuse_public_key or settings.langfuse_secret_key is None:
            raise PromptError("langfuse_credentials_required")
        if settings.narrative_image_content_policy is not None:
            raise PromptError("ambiguous_image_policy_source")
        if settings.env in {"staging", "production"} and not settings.langfuse_base_url.startswith(
            "https://"
        ):
            raise PromptError("langfuse_https_required")
        source = LangfusePromptSource(
            lock,
            reader
            or LangfuseReader(
                base_url=settings.langfuse_base_url,
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key.get_secret_value(),
                names=[entry.name for entry in lock.snapshot().entries],
            ),
            label=settings.langfuse_prompt_label,
            refresh_seconds=settings.langfuse_refresh_seconds,
        )
    previous = configure_source(source)
    try:
        if isinstance(source, LangfusePromptSource):
            source.start()
        yield source
    finally:
        if isinstance(source, LangfusePromptSource):
            await source.aclose()
        configure_source(previous)


class PromptSnapshotMiddleware:
    def __init__(self, app: ASGIApp, state: State):
        self.app, self.state = app, state

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        source = getattr(self.state, "prompt_source", None)
        with use_snapshot(source.snapshot() if source is not None else current_snapshot()):
            await self.app(scope, receive, send)


async def run_prompt_process(run: Callable[[], Awaitable[None]]) -> None:
    async with prompt_runtime(get_settings()):
        await run()
