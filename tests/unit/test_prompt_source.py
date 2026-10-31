"""Nonblocking approved-bundle selection at the PromptSource boundary."""

import asyncio

import pytest

from flint_graph.prompts.catalog import PromptEntry
from flint_graph.prompts.source import (
    LockedPromptSource,
    PromptBundle,
    current_snapshot,
    use_snapshot,
)


def bundle(text, version):
    return PromptBundle.create(
        [
            PromptEntry.create(
                name="example.reply",
                template=text,
                catalog_version=version,
                langfuse_version=version,
            )
        ],
        source_revision="fixture",
        evaluation_record="fixture",
    )


@pytest.mark.anyio
async def test_background_refresh_is_nonblocking_and_only_activates_whole_approved_bundles():
    from flint_graph.prompts.langfuse import LangfusePromptSource

    first, second, unknown = bundle("first", 1), bundle("second", 2), bundle("unreviewed", 3)
    lock = LockedPromptSource.from_bytes(LockedPromptSource.pack([first, second], first.sha256))
    entered, release = asyncio.Event(), asyncio.Event()
    selected = second

    class Reader:
        async def fetch(self, name, label):
            entered.set()
            await release.wait()
            return selected.entry(name)

    source = LangfusePromptSource(lock, Reader(), label="production")
    task = asyncio.create_task(source.refresh())
    await entered.wait()
    assert source.snapshot().sha256 == first.sha256, "snapshot never waits for the network"
    with use_snapshot(source.snapshot()):
        release.set()
        await task
        assert source.snapshot().sha256 == second.sha256
        assert current_snapshot().sha256 == first.sha256, "existing run keeps its original bundle"
    selected = unknown
    await source.refresh()
    assert source.snapshot().sha256 == second.sha256
    assert source.status()["last_result"] == "unreviewed"


@pytest.mark.anyio
async def test_unavailable_langfuse_retains_complete_local_fallback():
    from flint_graph.prompts.langfuse import LangfusePromptSource

    first = bundle("first", 1)
    lock = LockedPromptSource.from_bytes(LockedPromptSource.pack([first], first.sha256))

    class Reader:
        async def fetch(self, name, label):
            raise OSError("private response body must never reach status")

    source = LangfusePromptSource(lock, Reader(), label="production")
    await source.refresh()
    assert source.snapshot().sha256 == first.sha256
    assert source.status()["last_result"] == "unavailable"
    assert "private" not in str(source.status())


@pytest.mark.anyio
async def test_sdk_reader_uses_only_prompt_gets_and_preserves_approved_metadata():
    pytest.importorskip("langfuse")
    import httpx
    from opentelemetry import trace

    from flint_graph.prompts.langfuse import LangfuseReader, langfuse_config

    pytest.importorskip("langfuse")
    entry = bundle("first", 1).entry("example.reply")
    calls = []
    before = trace.get_tracer_provider()

    def handler(request):
        calls.append((request.method, request.url.path, dict(request.url.params), request.content))
        return httpx.Response(
            200,
            json={
                "name": entry.name,
                "version": 1,
                "type": "text",
                "prompt": "first",
                "labels": ["production"],
                "tags": [],
                "config": langfuse_config(entry),
            },
        )

    reader = LangfuseReader(
        base_url="http://langfuse.invalid",
        public_key="synthetic-public",
        secret_key="synthetic-secret",
        names=[entry.name],
        transport=httpx.MockTransport(handler),
    )
    try:
        fetched = await reader.fetch(entry.name, "production")
        assert fetched.sha256 == entry.sha256
        assert calls == [
            ("GET", "/api/public/v2/prompts/example.reply", {"label": "production"}, b"")
        ]
        assert trace.get_tracer_provider() is before
    finally:
        await reader.aclose()


@pytest.mark.anyio
async def test_transport_denies_writes_cross_origin_and_unrecognized_query_before_dispatch():
    import httpx

    from flint_graph.prompts.catalog import PromptError
    from flint_graph.prompts.langfuse import ReadOnlyPromptTransport

    calls = []
    inner = httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200))
    transport = ReadOnlyPromptTransport("https://langfuse.invalid", ["example.reply"], inner)
    async with httpx.AsyncClient(transport=transport) as client:
        for method, url in [
            ("POST", "https://langfuse.invalid/api/public/ingestion"),
            ("GET", "https://other.invalid/api/public/v2/prompts/example.reply"),
            (
                "GET",
                "https://langfuse.invalid/api/public/v2/prompts/example.reply?question=private",
            ),
        ]:
            with pytest.raises(PromptError, match="forbidden_prompt_transport"):
                await client.request(method, url)
    assert not calls


@pytest.mark.anyio
async def test_runtime_starts_on_local_bundle_without_waiting_for_remote_and_stops_its_poll():
    from pydantic import SecretStr

    from flint_graph.config import Settings
    from flint_graph.prompts.runtime import prompt_runtime

    entered = asyncio.Event()
    stopped = asyncio.Event()

    class Reader:
        async def fetch(self, name, label):
            entered.set()
            await asyncio.Event().wait()

        async def aclose(self):
            stopped.set()

    settings = Settings(
        env="test",
        prompt_source="langfuse",
        langfuse_public_key="synthetic",
        langfuse_secret_key=SecretStr("synthetic"),
        langfuse_base_url="http://langfuse.invalid",
    )
    async with prompt_runtime(settings, reader=Reader()) as source:
        assert source.snapshot().entry("narrative.assistant.system")
        await entered.wait()
        assert source.status()["last_result"] == "offline"
    assert stopped.is_set()


@pytest.mark.anyio
async def test_transport_caps_prompt_bytes_before_sdk_json_decoding():
    import httpx

    from flint_graph.prompts.catalog import PromptError
    from flint_graph.prompts.langfuse import MAX_RESPONSE_BYTES, ReadOnlyPromptTransport

    inner = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1))
    )
    async with httpx.AsyncClient(
        transport=ReadOnlyPromptTransport("https://langfuse.invalid", ["example.reply"], inner)
    ) as client:
        with pytest.raises(PromptError, match="prompt_response_too_large"):
            await client.get("https://langfuse.invalid/api/public/v2/prompts/example.reply")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status,reason",
    [(401, "invalid_credentials"), (403, "invalid_credentials"), (404, "missing_label")],
)
async def test_manager_diagnostics_distinguish_credentials_and_missing_labels(status, reason):
    from flint_graph.prompts.langfuse import LangfusePromptSource

    first = bundle("first", 1)
    lock = LockedPromptSource.from_bytes(LockedPromptSource.pack([first], first.sha256))

    class Error(Exception):
        status_code = status

    class Reader:
        async def fetch(self, name, label):
            raise Error("private response text")

    source = LangfusePromptSource(lock, Reader(), label="production")
    await source.refresh()
    assert source.status()["last_result"] == reason
    assert "private" not in str(source.status())
    assert source.snapshot().sha256 == first.sha256


@pytest.mark.anyio
async def test_runtime_refuses_an_obsolete_lock_missing_current_catalog_entries(tmp_path):
    from flint_graph.config import Settings
    from flint_graph.prompts.catalog import PromptError
    from flint_graph.prompts.runtime import prompt_runtime

    old = bundle("obsolete", 1)
    path = tmp_path / "obsolete.lock"
    path.write_bytes(LockedPromptSource.pack([old], old.sha256))
    with pytest.raises(PromptError, match="incomplete_catalog"):
        async with prompt_runtime(Settings(env="test", prompt_lock_path=str(path))):
            pytest.fail("A runtime must not admit work without its required templates")
