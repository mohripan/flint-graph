"""Opt-in isolated server qualification; only generic synthetic templates are uploaded."""

import asyncio
import os
from urllib.parse import quote

import httpx
import pytest

from flint_graph.narrative.assistant.turn import ModelReply, run_turn
from flint_graph.prompts.catalog import PromptEntry
from flint_graph.prompts.langfuse import LangfusePromptSource, LangfuseReader, langfuse_config
from flint_graph.prompts.release import get, promote, seed
from flint_graph.prompts.source import (
    LockedPromptSource,
    PromptBundle,
    current_snapshot,
    use_snapshot,
)

pytestmark = pytest.mark.skipif(
    os.getenv("FLINT_GRAPH_LANGFUSE_LIVE") != "1",
    reason="requires own isolated Langfuse 4.72.0 project and author/Viewer keys",
)


@pytest.mark.anyio
async def test_real_server_readonly_promotion_mismatch_rollback_and_outage():
    url = os.environ["FLINT_GRAPH_LANGFUSE_BASE_URL"]
    auth = (
        os.environ["FLINT_GRAPH_PROMPT_AUTHOR_PUBLIC_KEY"],
        os.environ["FLINT_GRAPH_PROMPT_AUTHOR_SECRET_KEY"],
    )
    viewer = (
        os.environ["FLINT_GRAPH_LANGFUSE_PUBLIC_KEY"],
        os.environ["FLINT_GRAPH_LANGFUSE_SECRET_KEY"],
    )
    original = LockedPromptSource.load().snapshot()
    entry = original.entry("narrative.assistant.system")
    data = entry.data
    data.pop("type")
    data["catalog_version"] += 1
    data["langfuse_version"] = 2
    data["template"] = [
        {"role": "system", "content": "Reviewed synthetic qualification instruction."}
    ]
    replacement = PromptEntry.create(**data)
    candidate = PromptBundle.create(
        [replacement if e.name == entry.name else e for e in original.entries],
        source_revision="synthetic-live-fixture",
        evaluation_record="test_prompt_langfuse_live.py",
    )
    lock = LockedPromptSource.from_bytes(
        LockedPromptSource.pack([original, candidate], original.sha256)
    )
    calls = []

    class AuditTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.inner = httpx.AsyncHTTPTransport(retries=0)
            self.outage = False

        async def handle_async_request(self, request):
            calls.append((request.method, request.url.path, len(request.content)))
            if self.outage:
                # Actual refused socket, while the independent authoring server stays running.
                request.url = httpx.URL("http://127.0.0.1:1" + request.url.raw_path.decode())
            return await self.inner.handle_async_request(request)

        async def aclose(self):
            await self.inner.aclose()

    transport = AuditTransport()
    reader = LangfuseReader(
        base_url=url,
        public_key=viewer[0],
        secret_key=viewer[1],
        names=[e.name for e in original.entries],
        transport=transport,
    )
    source = LangfusePromptSource(lock, reader, label="qualification")
    async with (
        httpx.AsyncClient(base_url=url, auth=auth, timeout=10) as author,
        httpx.AsyncClient(base_url=url, auth=viewer, timeout=10) as readonly,
    ):
        await seed(author, original, "staging")
        await seed(author, original, "staging")
        # Genuine server-side key restrictions, independently of the runtime transport guard.
        for method, path, payload in [
            (
                "POST",
                "/api/public/v2/prompts",
                {"name": "must-not-exist", "type": "text", "prompt": "Synthetic denied write"},
            ),
            (
                "PATCH",
                "/api/public/v2/prompts/" + entry.name + "/versions/1",
                {"newLabels": ["must-not-move"]},
            ),
            (
                "POST",
                "/api/public/scores",
                {
                    "name": "Synthetic denied score",
                    "value": 1,
                    "traceId": "synthetic-denied-trace",
                    "dataType": "NUMERIC",
                },
            ),
            (
                "POST",
                "/api/public/media",
                {
                    "traceId": "synthetic-denied-trace",
                    "field": "input",
                    "contentType": "image/png",
                    "contentLength": 1,
                    "sha256Hash": "0" * 64,
                },
            ),
        ]:
            denied = await readonly.request(method, path, json=payload)
            assert denied.status_code in {401, 403}, (method, denied.status_code)
        denied = await readonly.post(
            "/api/public/otel/v1/traces",
            content=b"",
            headers={"content-type": "application/x-protobuf"},
        )
        assert denied.status_code in {401, 403}

        async def create_version(version, template, config):
            existing = await get(author, entry.name, version=version)
            if existing is None:
                response = await author.post(
                    "/api/public/v2/prompts",
                    json={
                        "name": entry.name,
                        "type": "chat",
                        "prompt": template,
                        "config": config,
                        "labels": [],
                    },
                )
                response.raise_for_status()
                existing = response.json()
            assert (
                existing["version"] == version
                and existing["prompt"] == template
                and existing["config"] == config
            )

        await create_version(2, replacement.data["template"], langfuse_config(replacement))
        await promote(author, lock, original.sha256, "qualification")
        try:
            await source.refresh()
            assert source.status()["last_result"] == "approved"
            observed = []
            entered, release = asyncio.Event(), asyncio.Event()
            story = {
                "schema_version": "1",
                "id": "synthetic",
                "title": "Synthetic fixture",
                "language": "en",
                "entry": "finish",
                "characters": {},
                "variables": {},
                "assets": {},
                "nodes": {
                    "finish": {
                        "type": "end",
                        "text_id": "finish",
                        "text": "Synthetic ending.",
                        "ending": "done",
                    }
                },
            }

            class RecordingModel:
                provider = "scripted"

                async def respond(self, messages, schema, on_delta=None):
                    observed.append(messages[0]["content"])
                    entered.set()
                    await release.wait()
                    return ModelReply(
                        '{"reply":"Synthetic response.","proposal":null}', "synthetic", 1, 1
                    )

            with use_snapshot(source.snapshot()):
                old_run = asyncio.create_task(
                    run_turn(RecordingModel(), story, "Describe the synthetic ending.")
                )
                await entered.wait()
                try:
                    await promote(author, lock, candidate.sha256, "qualification")
                    await source.refresh()
                    assert source.snapshot().sha256 == candidate.sha256
                    assert current_snapshot().sha256 == original.sha256
                finally:
                    release.set()
                old_result = await old_run
            with use_snapshot(source.snapshot()):
                new_result = await run_turn(
                    RecordingModel(), story, "Describe the synthetic ending."
                )
            assert observed == [
                entry.data["template"][0]["content"],
                replacement.data["template"][0]["content"],
            ]
            assert old_result.prompt_sha256 != new_result.prompt_sha256
            unknown = [{"role": "system", "content": "Unreviewed synthetic fixture."}]
            await create_version(3, unknown, langfuse_config(replacement))
            response = await author.patch(
                "/api/public/v2/prompts/" + quote(entry.name) + "/versions/3",
                json={"newLabels": ["qualification"]},
            )
            response.raise_for_status()
            await source.refresh()
            assert source.snapshot().sha256 == candidate.sha256
            assert source.status()["last_result"] == "unreviewed"
            malformed = langfuse_config(replacement)
            malformed["flint_graph"]["variables_schema"] = {
                "$ref": "https://must-never-be-fetched.invalid/schema"
            }
            await create_version(4, unknown, malformed)
            response = await author.patch(
                "/api/public/v2/prompts/" + quote(entry.name) + "/versions/4",
                json={"newLabels": ["qualification"]},
            )
            response.raise_for_status()
            await source.refresh()
            assert source.snapshot().sha256 == candidate.sha256
            assert source.status()["last_result"] == "invalid_response"
            transport.outage = True
            await asyncio.wait_for(source.refresh(), 3)
            assert source.snapshot().sha256 == candidate.sha256
            assert source.status()["last_result"] == "unavailable"
            transport.outage = False
            await promote(author, lock, original.sha256, "qualification")
            await source.refresh()
            assert source.snapshot().sha256 == original.sha256
            assert source.status()["last_result"] == "approved"
        finally:
            await promote(author, lock, original.sha256, "qualification")
            await source.aclose()
    assert calls and all(
        method == "GET" and path.startswith("/api/public/v2/prompts/") and size == 0
        for method, path, size in calls
    )
