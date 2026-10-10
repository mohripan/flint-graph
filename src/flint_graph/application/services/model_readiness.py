"""Cheap model inventory checks; never instantiate or invoke a model provider."""

import asyncio
import json
import re
from typing import Literal

import httpx
from pydantic import BaseModel

from flint_graph.config import Settings
from flint_graph.infrastructure.answer_generator_factory import (
    answer_generator_model,
    support_checker_model,
)


class ModelReadiness(BaseModel):
    role: Literal["embedding", "answer", "support"]
    provider: str
    model: str
    status: Literal["available", "missing", "unavailable", "unknown", "offline"]
    digest: str | None = None


def _canonical_name(model: str) -> str:
    return model if ":" in model.rsplit("/", 1)[-1] else model + ":latest"


async def get_model_readiness(
    settings: Settings, *, http_client: httpx.AsyncClient | None = None
) -> list[ModelReadiness]:
    if http_client is None:
        async with httpx.AsyncClient(
            timeout=settings.readiness_probe_timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            return await get_model_readiness(settings, http_client=client)

    models = [
        (
            "embedding",
            settings.embedding_provider,
            settings.embedding_model,
            settings.embedding_ollama_base_url,
        ),
        (
            "answer",
            settings.query_answer_provider,
            answer_generator_model(settings),
            settings.ollama_base_url,
        ),
        (
            "support",
            settings.query_support_provider,
            support_checker_model(settings),
            settings.ollama_base_url,
        ),
    ]
    inventories: dict[str, dict[str, str | None] | None] = {}
    report = []
    for role, provider, model, base_url in models:
        status = "unknown"
        digest = None
        if provider == "deterministic":
            status = "offline"
        elif provider == "ollama":
            endpoint = base_url.rstrip("/") + "/api/tags"
            if endpoint not in inventories:
                inventories[endpoint] = await _inventory(http_client, endpoint, settings)
            names = inventories[endpoint]
            if names is None:
                status = "unavailable"
            else:
                status = "available" if _canonical_name(model) in names else "missing"
                digest = names.get(_canonical_name(model))
        report.append(
            ModelReadiness(role=role, provider=provider, model=model, status=status, digest=digest)
        )
    return report


async def _inventory(
    client: httpx.AsyncClient, endpoint: str, settings: Settings
) -> dict[str, str | None] | None:
    try:
        async with asyncio.timeout(settings.readiness_probe_timeout_seconds):
            async with client.stream(
                "GET",
                endpoint,
                timeout=settings.readiness_probe_timeout_seconds,
                follow_redirects=False,
            ) as response:
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 2 * 1024 * 1024:
                        return None
                payload = json.loads(body)
        items = payload["models"]
        if not isinstance(items, list):
            return None
        names = {}
        for item in items:
            name = item.get("name") if isinstance(item, dict) else None
            if not isinstance(name, str):
                return None
            digest = item.get("digest")
            fingerprint = None
            if isinstance(digest, str):
                digest = digest.removeprefix("sha256:")
                if re.fullmatch(r"[a-fA-F0-9]{64}", digest):
                    fingerprint = "sha256:" + digest.lower()
            names[_canonical_name(name)] = fingerprint
        return names
    except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError):
        # Provider response bodies, URLs and exception messages are never diagnostics.
        return None
