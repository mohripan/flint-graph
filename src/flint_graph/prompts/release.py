"""Explicit generic-template import and reviewed numeric-version promotion."""

from typing import Any
from urllib.parse import quote

import httpx

from flint_graph.prompts.catalog import PromptEntry, PromptError
from flint_graph.prompts.langfuse import langfuse_config
from flint_graph.prompts.source import LockedPromptSource, PromptBundle, entry_from_data


def remote_entry(data: dict[str, Any]) -> PromptEntry:
    try:
        config = data["config"]
        if set(config) != {"flint_graph", "value"}:
            raise ValueError
        return entry_from_data(
            {
                **config["flint_graph"],
                "name": data["name"],
                "type": data["type"],
                "template": data["prompt"],
                "langfuse_version": data["version"],
                "config": config["value"],
            }
        )
    except (ValueError, KeyError, TypeError):
        raise PromptError("invalid_prompt_response") from None


async def get(client: httpx.AsyncClient, name: str, **params: Any) -> dict[str, Any] | None:
    response = await client.get("/api/public/v2/prompts/" + quote(name, safe=""), params=params)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    if len(response.content) > 1024 * 1024:
        raise PromptError("prompt_response_too_large")
    value: dict[str, Any] = response.json()
    return value


async def seed(client: httpx.AsyncClient, bundle: PromptBundle, label: str) -> None:
    for entry in bundle.entries:
        data = await get(client, entry.name, version=entry.data["langfuse_version"])
        if data is not None:
            if remote_entry(data).sha256 != entry.sha256:
                raise PromptError("remote_version_mismatch")
            continue
        # Import only to empty names: never append unknown versions or overwrite authored work.
        if await get(client, entry.name, label="latest") is not None:
            raise PromptError("remote_name_already_exists")
        if entry.data["langfuse_version"] != 1:
            raise PromptError("seed_requires_version_one")
        response = await client.post(
            "/api/public/v2/prompts",
            json={
                "name": entry.name,
                "type": entry.data["type"],
                "prompt": entry.data["template"],
                "config": langfuse_config(entry),
                "labels": [label],
                "tags": ["flint-graph-catalog"],
            },
        )
        response.raise_for_status()
        if remote_entry(response.json()).sha256 != entry.sha256:
            raise PromptError("remote_version_mismatch")


async def pull(
    client: httpx.AsyncClient,
    lock: LockedPromptSource,
    label: str,
    *,
    source_revision: str,
    evaluation_record: str,
) -> PromptBundle:
    entries = []
    for entry in lock.snapshot().entries:
        data = await get(client, entry.name, label=label)
        if data is None:
            raise PromptError("remote_prompt_missing")
        entries.append(remote_entry(data))
    return PromptBundle.create(
        entries, source_revision=source_revision, evaluation_record=evaluation_record
    )


async def promote(
    client: httpx.AsyncClient, lock: LockedPromptSource, sha: str, label: str
) -> dict[str, Any]:
    bundle = lock.get(sha)
    previous = {}
    labels = {}
    for entry in bundle.entries:
        data = await get(client, entry.name, version=entry.data["langfuse_version"])
        if data is None or remote_entry(data).sha256 != entry.sha256:
            raise PromptError("remote_version_mismatch")
        labels[entry.name] = sorted((set(data.get("labels", [])) - {"latest"}) | {label})
        old = await get(client, entry.name, label=label)
        previous[entry.name] = old["version"] if old else None
    # Label APIs are per entry; the resolver only activates a complete approved map.
    for entry in bundle.entries:
        response = await client.patch(
            "/api/public/v2/prompts/"
            + quote(entry.name, safe="")
            + "/versions/"
            + str(entry.data["langfuse_version"]),
            json={"newLabels": labels[entry.name]},
        )
        response.raise_for_status()
    for entry in bundle.entries:
        data = await get(client, entry.name, label=label)
        if data is None or remote_entry(data).sha256 != entry.sha256:
            raise PromptError("promotion_readback_mismatch")
    return {
        "previous_versions": previous,
        "versions": {e.name: e.data["langfuse_version"] for e in bundle.entries},
        "bundle_sha256": sha,
        "label": label,
    }
