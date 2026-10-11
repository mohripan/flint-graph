"""Run only in an owned disposable Docker --network none namespace."""

import asyncio
import fcntl
import json
import os
import socket
import struct
import sys

from flint_graph.domain.errors import BadRequestError
from flint_graph.infrastructure.url_fetcher import HTTPURLFetcher


def configure_loopback():
    if not os.path.isfile("/.dockerenv"):
        raise SystemExit("Refusing to configure addresses outside a disposable Docker container.")
    if sys.argv[1:] != ["--isolated-network"]:
        raise SystemExit("Run only in Docker --network none with --isolated-network.")
    if {name for _, name in socket.if_nameindex()} != {"lo"}:
        raise SystemExit("Refusing to configure a namespace with a non-loopback interface.")
    if os.geteuid() != 0:
        raise SystemExit("Root plus NET_ADMIN is required inside the disposable namespace only.")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        fcntl.ioctl(
            sock,
            0x8916,
            struct.pack(
                "16sH2s4s8s",
                b"lo:public",
                socket.AF_INET,
                b"\0\0",
                socket.inet_aton("8.8.8.8"),
                b"\0" * 8,
            ),
        )
    with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as sock:
        fcntl.ioctl(
            sock,
            0x8916,
            struct.pack(
                "16sIi",
                socket.inet_pton(socket.AF_INET6, "2606:4700:4700::1111"),
                128,
                socket.if_nametoindex("lo"),
            ),
        )


async def rehearse(address, local):
    received, sentinel = [], []

    async def report(reader, writer):
        try:
            request = await reader.readuntil(b"\r\n\r\n")
            received.append(request.decode("ascii"))
            if b"GET /redirect " in request:
                writer.write(
                    b"HTTP/1.1 302 Found\r\nLocation: /sentinel\r\nContent-Length: 0\r\n\r\n"
                )
            else:
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\nPublic report")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def denied(reader, writer):
        sentinel.append("TCP contact")
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(report, address, 0)
    port = server.sockets[0].getsockname()[1]
    trap = await asyncio.start_server(denied, local, port)
    loop = asyncio.get_running_loop()
    original_resolver = loop.getaddrinfo
    answers = iter([])
    dns = []

    async def resolve(host, requested_port, *args, **kwargs):
        if host == "rebind.invalid":
            value = next(answers)
            dns.append(value)
            family = socket.AF_INET6 if ":" in value else socket.AF_INET
            sockaddr = (
                (value, requested_port, 0, 0)
                if family == socket.AF_INET6
                else (value, requested_port)
            )
            return [(family, socket.SOCK_STREAM, 6, "", sockaddr)]
        # Numeric addresses remain real socket connections, never mapped to a substitute.
        return await original_resolver(host, requested_port, *args, **kwargs)

    loop.getaddrinfo = resolve
    os.environ["HTTP_PROXY"] = f"http://127.0.0.1:{port}"
    os.environ["HTTPS_PROXY"] = os.environ["HTTP_PROXY"]
    os.environ["ALL_PROXY"] = os.environ["HTTP_PROXY"]
    os.environ["NO_PROXY"] = ""
    fetcher = HTTPURLFetcher(timeout_seconds=2, max_bytes=100)
    try:
        answers = iter([address, local])
        fetched = await fetcher.fetch(f"http://rebind.invalid:{port}/report")
        assert fetched.body == b"Public report"
        assert dns == [address], dns
        assert f"Host: rebind.invalid:{port}\r\n" in received[0]
        # A new request revalidates; no stale approved DNS result authorizes it.
        try:
            await fetcher.fetch(f"http://rebind.invalid:{port}/sentinel")
            raise AssertionError("Private reconnection was accepted")
        except BadRequestError as exc:
            assert "private or local" in str(exc)
        answers = iter([address, local])
        try:
            await fetcher.fetch(f"http://rebind.invalid:{port}/redirect")
            raise AssertionError("Private redirect was accepted")
        except BadRequestError as exc:
            assert "private or local" in str(exc)
        await asyncio.sleep(0)
        assert len(received) == 2, received
        assert sentinel == [], sentinel
        assert all("Authorization:" not in request for request in received)
        return {
            "address": address,
            "report_http_requests": len(received),
            "sentinel_tcp_contacts": len(sentinel),
            "dns_answers": dns,
            "host_preserved": True,
            "ambient_proxy_ignored": True,
            "fresh_request_and_redirect_denied": True,
        }
    finally:
        loop.getaddrinfo = original_resolver
        server.close()
        trap.close()
        await server.wait_closed()
        await trap.wait_closed()


async def main():
    configure_loopback()
    results = [
        await rehearse("8.8.8.8", "127.0.0.1"),
        await rehearse("2606:4700:4700::1111", "::1"),
    ]
    print(json.dumps({"status": "passed", "network": "none", "cases": results}))


asyncio.run(main())
