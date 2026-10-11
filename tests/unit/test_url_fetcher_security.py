from __future__ import annotations

import asyncio
import socket

import httpcore
import httpx
import pytest

from flint_graph.domain.errors import BadRequestError
from flint_graph.infrastructure.url_fetcher import HTTPURLFetcher


@pytest.mark.anyio
async def test_url_fetcher_connects_to_validated_address_not_a_second_dns_answer(monkeypatch):
    answers = iter(["8.8.8.8", "127.0.0.1"])
    connected = []

    def resolve(host, port, *args, **kwargs):
        address = next(answers) if host in ("rebind.invalid", b"rebind.invalid") else host
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    async def connect(backend, host, port, **kwargs):
        address = host
        if host == "rebind.invalid":
            address = resolve(host, port)[0][4][0]
        connected.append(address)
        body = b"Public report" if address == "8.8.8.8" else b"LOCAL SENTINEL"
        return httpcore.AsyncMockStream(
            [b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body]
        )

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", connect)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
    fetched = await HTTPURLFetcher(timeout_seconds=1, max_bytes=100).fetch(
        "http://rebind.invalid/report"
    )
    assert fetched.body == b"Public report"
    assert connected == ["8.8.8.8"]
    assert fetched.final_url == "http://rebind.invalid/report"


@pytest.mark.anyio
async def test_url_fetcher_total_deadline_includes_dns(monkeypatch):
    async def slow_dns(*args, **kwargs):
        await asyncio.sleep(0.1)
        return []

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", slow_dns)
    with pytest.raises(BadRequestError, match="timed out"):
        await HTTPURLFetcher(timeout_seconds=0.01, max_bytes=100).fetch("http://slow.invalid/")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "addresses",
    [
        ["8.8.8.8", "127.0.0.1"],
        ["2606:4700:4700::1111", "::1"],
        ["::ffff:127.0.0.1"],
        ["100.64.0.1"],
        ["0.0.0.0"],
        ["192.0.2.1"],
        ["2001:db8::1"],
        ["ff02::1"],
        ["fe80::1"],
        ["64:ff9b::7f00:1"],
        ["2002:7f00:1::"],
    ],
)
async def test_url_fetcher_rejects_any_nonpublic_dns_answer_before_tcp(monkeypatch, addresses):
    async def resolve(*args, **kwargs):
        return [
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (address, 80),
            )
            for address in addresses
        ]

    async def forbidden_connect(*args, **kwargs):
        pytest.fail("Denied address set must not reach the TCP boundary")

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", forbidden_connect)
    with pytest.raises(BadRequestError, match="private or local"):
        await HTTPURLFetcher(timeout_seconds=1, max_bytes=100).fetch("http://mixed.invalid/")


@pytest.mark.anyio
@pytest.mark.parametrize("address", ["8.8.8.8", "2606:4700:4700::1111"])
async def test_url_fetcher_validates_redirect_rebinding_without_contacting_sentinel(
    monkeypatch, address
):
    answers = iter([address, "127.0.0.1"])
    connected = []

    async def resolve(*args, **kwargs):
        value = next(answers)
        family = socket.AF_INET6 if ":" in value else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (value, 80))]

    async def connect(backend, host, port, **kwargs):
        connected.append(host)
        return httpcore.AsyncMockStream(
            [b"HTTP/1.1 302 Found\r\nLocation: /sentinel\r\nContent-Length: 0\r\n\r\n"]
        )

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", connect)
    with pytest.raises(BadRequestError, match="private or local"):
        await HTTPURLFetcher(timeout_seconds=1, max_bytes=100).fetch("http://rebind.invalid/report")
    assert connected == [address]


@pytest.mark.anyio
async def test_url_fetcher_ignores_ambient_proxy_and_does_not_retry_connections(monkeypatch):
    connected = []

    async def connect(backend, host, port, **kwargs):
        connected.append((host, port))
        raise httpcore.ConnectError("Synthetic connection failure")

    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:9999")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", connect)
    with pytest.raises(BadRequestError, match="could not be fetched"):
        await HTTPURLFetcher(timeout_seconds=1, max_bytes=100).fetch("http://8.8.8.8/report")
    assert connected == [("8.8.8.8", 80)]


@pytest.mark.anyio
async def test_url_fetcher_dns_failure_has_a_safe_error(monkeypatch):
    async def resolve(*args, **kwargs):
        raise socket.gaierror("SYNTHETIC_DIAGNOSTIC_NOT_FOR_USER")

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(BadRequestError, match="could not be fetched") as error:
        await HTTPURLFetcher(timeout_seconds=1, max_bytes=100).fetch("http://missing.invalid/")
    assert "SYNTHETIC_DIAGNOSTIC" not in str(error.value)


@pytest.mark.anyio
async def test_url_fetcher_total_deadline_includes_trickling_body():
    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(100):
                await asyncio.sleep(0.01)
                yield b"x"

    def respond(request):
        return httpx.Response(200, stream=SlowBody())

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        fetcher = HTTPURLFetcher(timeout_seconds=0.025, max_bytes=100, http_client=client)
        with pytest.raises(BadRequestError, match="timed out"):
            await fetcher.fetch("http://8.8.8.8/report")


@pytest.mark.anyio
async def test_url_fetcher_keeps_redirect_count_bounded():
    requests = []

    def redirect(request):
        requests.append(request.url.path)
        return httpx.Response(302, headers={"Location": "/again"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(redirect)) as client:
        with pytest.raises(BadRequestError, match="too many times"):
            await HTTPURLFetcher(timeout_seconds=1, max_bytes=100, http_client=client).fetch(
                "http://8.8.8.8/report"
            )
    assert len(requests) == 6


@pytest.mark.anyio
async def test_url_fetcher_limits_body_without_content_length():
    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"12345"
            yield b"67890"

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Body()))
    ) as client:
        with pytest.raises(BadRequestError, match="exceeds the intake limit"):
            await HTTPURLFetcher(timeout_seconds=1, max_bytes=9, http_client=client).fetch(
                "http://8.8.8.8/report"
            )


@pytest.mark.parametrize("timeout", [float("inf"), float("nan"), 0, -1])
def test_url_fetcher_requires_a_finite_positive_deadline(timeout):
    with pytest.raises(ValueError, match="finite and positive"):
        HTTPURLFetcher(timeout_seconds=timeout, max_bytes=100)


@pytest.mark.parametrize("max_bytes", [0, -1])
def test_url_fetcher_requires_a_positive_body_limit(max_bytes):
    with pytest.raises(ValueError, match="positive"):
        HTTPURLFetcher(timeout_seconds=1, max_bytes=max_bytes)


@pytest.mark.anyio
@pytest.mark.parametrize("address", ["2002:7f00:1::", "64:ff9b::7f00:1"])
async def test_url_fetcher_rejects_transition_addresses_that_can_embed_local_ipv4(
    address, monkeypatch
):
    async def forbidden_connect(*args, **kwargs):
        pytest.fail("Transition address must be rejected before TCP")

    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", forbidden_connect)
    with pytest.raises(BadRequestError, match="private or local"):
        await HTTPURLFetcher(timeout_seconds=1, max_bytes=100).fetch(f"http://[{address}]/")


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
