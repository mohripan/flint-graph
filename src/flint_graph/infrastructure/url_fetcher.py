from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
from socket import getaddrinfo
from typing import Protocol
from urllib.parse import urljoin, urlparse

import httpx

from flint_graph.domain.errors import BadRequestError


@dataclass(frozen=True)
class FetchedURL:
    body: bytes
    content_type: str
    final_url: str


class URLFetcher(Protocol):
    async def fetch(self, url: str) -> FetchedURL: ...


class HTTPURLFetcher:
    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_bytes: int,
        allow_private_addresses: bool = False,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes
        self._allow_private_addresses = allow_private_addresses
        self._http_client = http_client

    async def fetch(self, url: str) -> FetchedURL:
        self._validate_url(url, resolve_hostname=self._http_client is None)
        try:
            if self._http_client is not None:
                return await self._fetch_with_client(self._http_client, url)
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                return await self._fetch_with_client(client, url)
        except BadRequestError:
            raise
        except httpx.HTTPStatusError as exc:
            raise BadRequestError(
                f"URL returned an unsuccessful status: {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise BadRequestError("URL content could not be fetched.") from exc

    async def _fetch_with_client(self, client: httpx.AsyncClient, url: str) -> FetchedURL:
        current_url = url
        for _ in range(6):
            async with client.stream("GET", current_url, follow_redirects=False) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise BadRequestError("URL redirect omitted a Location header.")
                    current_url = urljoin(str(response.url), location)
                    self._validate_url(
                        current_url,
                        resolve_hostname=self._http_client is None,
                    )
                    continue
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                if content_length is not None and int(content_length) > self._max_bytes:
                    raise BadRequestError("Fetched URL content exceeds the intake limit.")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > self._max_bytes:
                        raise BadRequestError("Fetched URL content exceeds the intake limit.")
                return FetchedURL(
                    body=bytes(body),
                    content_type=response.headers.get(
                        "content-type",
                        "application/octet-stream",
                    ),
                    final_url=str(response.url),
                )
        raise BadRequestError("URL redirected too many times.")

    def _validate_url(self, url: str, *, resolve_hostname: bool) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise BadRequestError("URL intake only supports http or https URLs.")
        if not parsed.hostname:
            raise BadRequestError("URL intake requires a hostname.")
        if self._allow_private_addresses:
            return
        try:
            address = ip_address(parsed.hostname)
        except ValueError:
            if not resolve_hostname:
                return
            addresses = {
                item[4][0]
                for item in getaddrinfo(parsed.hostname, parsed.port or 443)
                if item and item[4]
            }
        else:
            addresses = {str(address)}
        for value in addresses:
            address = ip_address(value)
            if (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_multicast
            ):
                raise BadRequestError("URL intake rejects private or local network targets.")
