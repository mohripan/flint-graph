"""Release tools import generic catalog data and keep label writes review-bound."""

import json

import httpx
import pytest

from flint_graph.prompts.catalog import PromptEntry, PromptError
from flint_graph.prompts.source import LockedPromptSource, PromptBundle


@pytest.mark.anyio
async def test_seed_is_idempotent_and_does_not_overwrite_an_existing_numeric_version():
    from flint_graph.prompts.release import seed

    entry = PromptEntry.create(
        name="synthetic", template="A generic instruction", catalog_version=1
    )
    bundle = PromptBundle.create([entry], source_revision="fixture", evaluation_record="fixture")
    rows = {}
    writes = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=rows[entry.name]) if rows else httpx.Response(404)
        writes.append(json.loads(request.content))
        rows[entry.name] = {**writes[-1], "version": 1}
        return httpx.Response(200, json=rows[entry.name])

    async with httpx.AsyncClient(
        base_url="http://fixture", transport=httpx.MockTransport(handler)
    ) as client:
        await seed(client, bundle, "staging")
        await seed(client, bundle, "staging")
        assert len(writes) == 1
        rows[entry.name]["prompt"] = "Changed outside review"
        with pytest.raises(PromptError, match="remote_version_mismatch"):
            await seed(client, bundle, "staging")
    assert writes[0]["prompt"] == "A generic instruction"


@pytest.mark.anyio
async def test_promotion_validates_entire_bundle_before_any_label_write():
    from flint_graph.prompts.langfuse import langfuse_config
    from flint_graph.prompts.release import promote

    entries = [
        PromptEntry.create(name=name, template="Generic", catalog_version=1)
        for name in ("one", "two")
    ]
    bundle = PromptBundle.create(entries, source_revision="fixture", evaluation_record="fixture")
    lock = LockedPromptSource.from_bytes(LockedPromptSource.pack([bundle], bundle.sha256))
    writes = []

    def handler(request):
        if request.method != "GET":
            writes.append(request.method)
        entry = entries[0] if "/one" in request.url.path else entries[1]
        return httpx.Response(
            200,
            json={
                "name": entry.name,
                "version": 1,
                "type": "text",
                "prompt": "Generic" if entry.name == "one" else "Unreviewed",
                "config": langfuse_config(entry),
                "labels": [],
            },
        )

    async with httpx.AsyncClient(
        base_url="http://fixture", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(PromptError, match="remote_version_mismatch"):
            await promote(client, lock, bundle.sha256, "production")
    assert writes == []


@pytest.mark.anyio
async def test_promotion_preserves_environment_labels_without_writing_reserved_latest():
    from flint_graph.prompts.langfuse import langfuse_config
    from flint_graph.prompts.release import promote

    entry = PromptEntry.create(name="synthetic", template="Generic", catalog_version=1)
    bundle = PromptBundle.create([entry], source_revision="fixture", evaluation_record="fixture")
    lock = LockedPromptSource.from_bytes(LockedPromptSource.pack([bundle], bundle.sha256))
    labels = ["latest", "staging"]

    def handler(request):
        if request.method == "PATCH":
            labels[:] = json.loads(request.content)["newLabels"]
            assert labels == ["production", "staging"]
        return httpx.Response(
            200,
            json={
                "name": entry.name,
                "type": "text",
                "version": 1,
                "prompt": "Generic",
                "config": langfuse_config(entry),
                "labels": labels,
            },
        )

    async with httpx.AsyncClient(
        base_url="http://fixture", transport=httpx.MockTransport(handler)
    ) as client:
        await promote(client, lock, bundle.sha256, "production")


def test_a_candidate_may_add_a_prompt_but_may_not_lose_one(tmp_path):
    from flint_graph.cli.prompts import main

    def bundle(*names):
        entries = [
            PromptEntry.create(name=name, template="An instruction", catalog_version=1)
            for name in names
        ]
        return PromptBundle.create(entries, source_revision="fixture", evaluation_record="fixture")

    first = bundle("first", "second")
    lock = tmp_path / "prompts.lock"
    lock.write_bytes(LockedPromptSource.pack([first], first.sha256))

    def run(candidate):
        path = tmp_path / "candidate.json"
        path.write_text(json.dumps(candidate.data), "utf-8")
        return main(
            ["--lock", str(lock), "lock", str(path), "--output", str(tmp_path / "out.lock")]
        )

    assert run(bundle("first", "second", "third")) == 0
    assert run(bundle("first")) != 0
