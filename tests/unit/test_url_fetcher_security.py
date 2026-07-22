from __future__ import annotations

import httpx
import pytest

from flint_graph.domain.errors import BadRequestError
from flint_graph.infrastructure.url_fetcher import HTTPURLFetcher


@pytest.mark.anyio
async def test_url_fetcher_rejects_unsupported_schemes() -> None:
    fetcher = HTTPURLFetcher(timeout_seconds=1.0, max_bytes=100)

    with pytest.raises(BadRequestError, match="http or https"):
        await fetcher.fetch("file:///etc/passwd")


@pytest.mark.anyio
async def test_url_fetcher_rejects_private_ip_targets() -> None:
    fetcher = HTTPURLFetcher(timeout_seconds=1.0, max_bytes=100)

    with pytest.raises(BadRequestError, match="private"):
        await fetcher.fetch("http://127.0.0.1/document.md")


@pytest.mark.anyio
async def test_url_fetcher_rejects_redirects_to_private_ip_targets() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "public.example":
            return httpx.Response(
                302,
                headers={"Location": "http://127.0.0.1/metadata"},
                request=request,
            )
        return httpx.Response(200, text="secret", request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        fetcher = HTTPURLFetcher(
            timeout_seconds=1.0,
            max_bytes=100,
            http_client=http_client,
        )

        with pytest.raises(BadRequestError, match="private"):
            await fetcher.fetch("https://public.example/document.md")


@pytest.mark.anyio
async def test_url_fetcher_rejects_remote_response_above_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 12, request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        fetcher = HTTPURLFetcher(
            timeout_seconds=1.0,
            max_bytes=10,
            allow_private_addresses=True,
            http_client=http_client,
        )

        with pytest.raises(BadRequestError, match="exceeds"):
            await fetcher.fetch("https://public.example/document.md")
