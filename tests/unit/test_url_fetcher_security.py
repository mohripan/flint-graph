from __future__ import annotations

import httpx
import pytest

from flint_graph.domain.errors import BadRequestError
from flint_graph.infrastructure.url_fetcher import HTTPURLFetcher


@pytest.mark.anyio
@pytest.mark.parametrize(
    "userinfo",
    [
        "example-user:EXAMPLE_NOT_SECRET",
        "example-user",
        ":EXAMPLE_NOT_SECRET",
        "",
        "%65xample-user:%45XAMPLE_NOT_SECRET",
    ],
)
@pytest.mark.parametrize("allow_private", [False, True])
async def test_url_fetcher_rejects_user_info_before_any_network_request(userinfo, allow_private):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, text="Synthetic public report")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
        fetcher = HTTPURLFetcher(
            timeout_seconds=1,
            max_bytes=100,
            allow_private_addresses=allow_private,
            http_client=http_client,
        )
        with pytest.raises(BadRequestError, match="user information") as error:
            await fetcher.fetch(f"http://{userinfo}@8.8.8.8/document.md")
    assert requests == []
    assert "EXAMPLE_NOT_SECRET" not in str(error.value)
    assert "example-user" not in str(error.value)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "userinfo", ["example-user:EXAMPLE_NOT_SECRET", "example-user", ":EXAMPLE_NOT_SECRET", ""]
)
@pytest.mark.parametrize("allow_private", [False, True])
async def test_url_fetcher_rejects_redirect_user_info_before_affected_request(
    userinfo, allow_private
):
    requests = []

    def respond(request):
        requests.append(request.url.path)
        return httpx.Response(302, headers={"Location": f"https://{userinfo}@8.8.8.8/redirected"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
        fetcher = HTTPURLFetcher(
            timeout_seconds=1,
            max_bytes=100,
            allow_private_addresses=allow_private,
            http_client=http_client,
        )
        with pytest.raises(BadRequestError, match="user information") as error:
            await fetcher.fetch("https://8.8.8.8/document.md")
    assert requests == ["/document.md"]
    assert "EXAMPLE_NOT_SECRET" not in str(error.value)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "url,allow_private",
    [("https://8.8.8.8/document.md", False), ("http://127.0.0.1/document.md", True)],
)
async def test_url_fetcher_preserves_explicitly_allowed_credential_free_intake(url, allow_private):
    def respond(request):
        assert "authorization" not in request.headers
        return httpx.Response(
            200, text="Synthetic public report", headers={"Content-Type": "text/plain"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
        fetcher = HTTPURLFetcher(
            timeout_seconds=1,
            max_bytes=100,
            allow_private_addresses=allow_private,
            http_client=http_client,
        )
        fetched = await fetcher.fetch(url)
    assert fetched.body == b"Synthetic public report"
    assert fetched.final_url == url


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
