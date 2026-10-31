"""Bounded, read-only Langfuse refresh. Snapshot reads are entirely local."""

import asyncio
import importlib
from collections.abc import Sequence
from contextlib import suppress
from typing import Any, Protocol
from urllib.parse import quote

import httpx
import structlog

from flint_graph.observability import metrics
from flint_graph.observability.instruments import PROMPT_REFRESH_RESULTS
from flint_graph.prompts.catalog import PromptEntry, PromptError
from flint_graph.prompts.source import LockedPromptSource, PromptBundle, entry_from_data

MAX_RESPONSE_BYTES = 1024 * 1024
_logger = structlog.get_logger(__name__)


class PromptReader(Protocol):
    async def fetch(self, name: str, label: str) -> PromptEntry: ...


class ReadOnlyPromptTransport(httpx.AsyncBaseTransport):
    """Deny payload writes and redirects before any credentialed network dispatch."""

    def __init__(
        self, base_url: str, names: Sequence[str], transport: httpx.AsyncBaseTransport | None = None
    ):
        self._base = httpx.URL(base_url)
        if self._base.username or self._base.password or self._base.query or self._base.fragment:
            raise PromptError("invalid_langfuse_origin")
        self._paths = {
            self._base.path.rstrip("/") + "/api/public/v2/prompts/" + quote(name, safe="")
            for name in names
        }
        self._inner = transport or httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        def origin(url: httpx.URL) -> tuple[str, str, int | None]:
            return url.scheme, url.host, url.port

        if (
            request.method != "GET"
            or origin(request.url) != origin(self._base)
            or request.url.path not in self._paths
            or not set(request.url.params).issubset({"version", "label"})
        ):
            raise PromptError("forbidden_prompt_transport")
        request.headers["accept-encoding"] = "identity"
        response = await self._inner.handle_async_request(request)
        try:
            if response.headers.get("content-encoding", "identity") != "identity":
                raise PromptError("encoded_prompt_response")
            content = bytearray()
            if response.is_stream_consumed:
                content.extend(response.content)
            else:
                async for chunk in response.aiter_raw():
                    content.extend(chunk)
                    if len(content) > MAX_RESPONSE_BYTES:
                        raise PromptError("prompt_response_too_large")
            if len(content) > MAX_RESPONSE_BYTES:
                raise PromptError("prompt_response_too_large")
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=bytes(content),
                request=request,
            )
        finally:
            await response.aclose()

    async def aclose(self) -> None:
        await self._inner.aclose()


class LangfuseReader:
    def __init__(
        self,
        *,
        base_url: str,
        public_key: str,
        secret_key: str,
        names: Sequence[str],
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        try:
            api_type = importlib.import_module("langfuse.api.client").AsyncLangfuseAPI
        except ImportError:
            raise PromptError("langfuse_extra_required") from None
        self._http = httpx.AsyncClient(
            transport=ReadOnlyPromptTransport(base_url, names, transport),
            timeout=2,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=4),
        )
        # Generated API only: no Langfuse facade, telemetry exporter or background
        # media/score consumers are constructed.
        self._api = api_type(
            base_url=base_url,
            username=public_key,
            password=secret_key,
            httpx_client=self._http,
            timeout=2,
            follow_redirects=False,
        )

    async def fetch(self, name: str, label: str) -> PromptEntry:
        result = await self._api.prompts.get(
            name, label=label, request_options={"max_retries": 0, "timeout_in_seconds": 2}
        )
        payload = result.model_dump(mode="json")
        try:
            if payload["name"] != name or label not in payload["labels"]:
                raise PromptError("invalid_prompt_response")
            config = payload["config"]
            if set(config) != {"flint_graph", "value"}:
                raise PromptError("invalid_prompt_response")
            return entry_from_data(
                {
                    **config["flint_graph"],
                    "name": name,
                    "type": payload["type"],
                    "template": payload["prompt"],
                    "langfuse_version": payload["version"],
                    "config": config["value"],
                }
            )
        except (KeyError, TypeError, AttributeError, ValueError):
            raise PromptError("invalid_prompt_response") from None

    async def aclose(self) -> None:
        await self._http.aclose()


def langfuse_config(entry: PromptEntry) -> dict[str, Any]:
    data = entry.data
    return {
        "flint_graph": {
            key: value
            for key, value in data.items()
            if key not in {"name", "type", "template", "langfuse_version", "config"}
        },
        "value": data["config"],
    }


class LangfusePromptSource:
    def __init__(
        self,
        lock: LockedPromptSource,
        reader: PromptReader,
        *,
        label: str,
        refresh_seconds: float = 60,
    ):
        self._lock, self._reader, self._label = lock, reader, label
        self._active = lock.snapshot()
        self._names = tuple(entry.name for entry in self._active.entries)
        self._interval = max(1, min(60, refresh_seconds))
        self._task: asyncio.Task[None] | None = None
        self._last_result = "offline"
        self._refresh_lock = asyncio.Lock()

    def snapshot(self) -> PromptBundle:
        return self._active

    def status(self) -> dict[str, Any]:
        return {
            "mode": "langfuse",
            "bundle_sha256": self._active.sha256,
            "last_result": self._last_result,
            "connected": self._last_result in {"approved", "unreviewed"},
        }

    def _record(self, result: str) -> None:
        self._last_result = result
        metrics.add(PROMPT_REFRESH_RESULTS, **{"flint_graph.prompt_refresh.result": result})
        if result != "approved":
            _logger.warning("prompt_refresh_fallback", reason=result)

    async def refresh(self) -> None:
        if self._refresh_lock.locked():
            return
        async with self._refresh_lock:
            semaphore = asyncio.Semaphore(4)

            async def fetch(name: str) -> PromptEntry:
                async with semaphore:
                    return await self._reader.fetch(name, self._label)

            tasks = [asyncio.create_task(fetch(name)) for name in self._names]
            try:
                async with asyncio.timeout(2):
                    entries = await asyncio.gather(*tasks)
                observed = {entry.name: entry.sha256 for entry in entries}
                for bundle in self._lock.bundles:
                    if observed == {entry.name: entry.sha256 for entry in bundle.entries}:
                        self._active = bundle
                        self._record("approved")
                        return
                self._record("unreviewed")
            except PromptError:
                self._record("invalid_response")
            except Exception as error:
                status = getattr(error, "status_code", None)
                self._record(
                    "invalid_credentials"
                    if status in {401, 403}
                    else "missing_label"
                    if status == 404
                    else "unavailable"
                )
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._poll(), name="prompt-refresh")

    async def _poll(self) -> None:
        while True:
            await self.refresh()
            await asyncio.sleep(self._interval)

    async def aclose(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        close = getattr(self._reader, "aclose", None)
        if close is not None:
            await close()
