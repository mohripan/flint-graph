import asyncio

import httpx
import pytest

from flint_graph.application.services.model_readiness import get_model_readiness
from flint_graph.config import Settings


async def test_offline_and_hosted_checks_never_call_a_provider() -> None:
    def reject(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"Unexpected provider request: {request.method}")

    settings = Settings(
        env="test", query_answer_provider="anthropic", anthropic_api_key="secret-key"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as client:
        report = await get_model_readiness(settings, http_client=client)
    assert [item.status for item in report] == ["offline", "unknown", "offline"]
    assert "secret-key" not in str(report)


async def test_ollama_checks_exact_models_and_deduplicates_read_only_tag_requests() -> None:
    requests = []

    def tags(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "local:latest"}]})

    settings = Settings(
        env="test",
        embedding_provider="ollama",
        embedding_model="missing",
        query_answer_provider="ollama",
        query_answer_model="local",
        query_support_provider="ollama",
        query_support_model="local:other",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(tags)) as client:
        report = await get_model_readiness(settings, http_client=client)
    assert [item.status for item in report] == ["missing", "available", "missing"]
    assert len(requests) == 1
    assert [item.role for item in report] == ["embedding", "answer", "support"]
    assert "http" not in str(report)


@pytest.mark.parametrize("failure", ["timeout", "error", "invalid", "redirect"])
async def test_provider_failures_return_safe_unavailability(failure: str) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        if failure == "timeout":
            raise httpx.ReadTimeout("private-provider-secret", request=request)
        if failure == "error":
            return httpx.Response(500, text="private-provider-secret")
        if failure == "redirect":
            return httpx.Response(302, headers={"Location": "https://private-provider-secret"})
        return httpx.Response(200, json={"models": "private-provider-secret"})

    settings = Settings(env="test", query_answer_provider="ollama")
    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        report = await get_model_readiness(settings, http_client=client)
    assert report[1].status == "unavailable"
    assert "private-provider-secret" not in str(report)


async def test_inventory_has_an_overall_deadline_not_only_socket_timeouts() -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.2)
        return httpx.Response(200, json={"models": []})

    settings = Settings(
        env="test", query_answer_provider="ollama", readiness_probe_timeout_seconds=0.01
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
        report = await get_model_readiness(settings, http_client=client)
    assert report[1].status == "unavailable"


async def test_oversized_provider_inventory_is_rejected() -> None:
    def oversized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [], "private": "x" * (2 * 1024 * 1024)})

    settings = Settings(env="test", query_answer_provider="ollama")
    async with httpx.AsyncClient(transport=httpx.MockTransport(oversized)) as client:
        report = await get_model_readiness(settings, http_client=client)
    assert report[1].status == "unavailable"


async def test_bare_inventory_name_matches_explicit_latest_tag() -> None:
    def tags(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "local"}]})

    settings = Settings(
        env="test", query_answer_provider="ollama", query_answer_model="local:latest"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(tags)) as client:
        report = await get_model_readiness(settings, http_client=client)
    assert report[1].status == "available"


async def test_model_inventory_reports_only_valid_sha256_fingerprints() -> None:
    def tags(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "answer:latest", "digest": "a" * 64, "private": "private-secret"},
                    {"name": "support:latest", "digest": "private-secret"},
                ]
            },
        )

    settings = Settings(
        env="test",
        query_answer_provider="ollama",
        query_answer_model="answer",
        query_support_provider="ollama",
        query_support_model="support",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(tags)) as client:
        report = await get_model_readiness(settings, http_client=client)
    assert report[1].digest == "sha256:" + "a" * 64
    assert report[2].status == "available"
    assert report[2].digest is None
    assert "private-secret" not in str(report)
