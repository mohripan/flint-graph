from __future__ import annotations

import asyncio
import socket
from ipaddress import IPv6Address, IPv6Network, ip_address

import httpx

from flint_graph.domain.errors import BadRequestError


def is_public_intake_address(value: str) -> bool:
    address = ip_address(value)
    if not address.is_global or address.is_multicast or "%" in value:
        return False
    if isinstance(address, IPv6Address):
        # Transition/translation networks can hide a nonpublic IPv4 destination.
        # Native IPv6 remains supported; custom translators need separate egress policy.
        if address.sixtofour is not None or address.teredo is not None:
            return False
        if address in IPv6Network("64:ff9b::/96"):
            return False
        if address.ipv4_mapped is not None and not address.ipv4_mapped.is_global:
            return False
    return True


class PinnedURLTransport(httpx.AsyncBaseTransport):
    """Resolve once per request and send only to a validated numeric address."""

    def __init__(self, *, allow_private_addresses: bool) -> None:
        self._allow_private_addresses = allow_private_addresses
        # IP-based pooling must not reuse a TLS connection for another hostname.
        self._transport = httpx.AsyncHTTPTransport(
            trust_env=False, retries=0, limits=httpx.Limits(max_keepalive_connections=0)
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.raw_host.decode("ascii")
        try:
            addresses = [str(ip_address(host))]
        except ValueError:
            results = await asyncio.get_running_loop().getaddrinfo(
                host,
                request.url.port or (443 if request.url.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
            addresses = list(dict.fromkeys(str(result[4][0]) for result in results))
        if not addresses:
            raise BadRequestError("URL hostname did not resolve to an address.")
        if not self._allow_private_addresses:
            for value in addresses:
                if not is_public_intake_address(value):
                    raise BadRequestError("URL intake rejects private or local network targets.")
        pinned = httpx.Request(
            method=request.method,
            url=request.url.copy_with(host=addresses[0]),
            headers=request.headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": host},
        )
        return await self._transport.handle_async_request(pinned)

    async def aclose(self) -> None:
        await self._transport.aclose()
