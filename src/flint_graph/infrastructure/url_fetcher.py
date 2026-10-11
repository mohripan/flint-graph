from __future__ import annotations

import asyncio
from dataclasses import dataclass
from ipaddress import ip_address
from math import isfinite
from typing import Protocol
from urllib.parse import urljoin, urlparse

import httpx

from flint_graph.domain.errors import BadRequestError
from flint_graph.infrastructure.url_transport import PinnedURLTransport, is_public_intake_address


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
        if not isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("URL intake deadline must be finite and positive.")
        if max_bytes <= 0:
            raise ValueError("URL intake body limit must be positive.")
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes
        self._allow_private_addresses = allow_private_addresses
        self._http_client = http_client

    async def fetch(self, url: str) -> FetchedURL:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                self._validate_url(url)
                if self._http_client is not None:
                    return await self._fetch_with_client(self._http_client, url)
                transport = PinnedURLTransport(
                    allow_private_addresses=self._allow_private_addresses
                )
                async with httpx.AsyncClient(
                    timeout=self._timeout_seconds, transport=transport, trust_env=False
                ) as client:
                    return await self._fetch_with_client(client, url)
        except BadRequestError:
            raise
        except TimeoutError as exc:
            raise BadRequestError("URL intake timed out.") from exc
        except httpx.HTTPStatusError as exc:
            raise BadRequestError(
                f"URL returned an unsuccessful status: {exc.response.status_code}."
            ) from exc
        except (httpx.HTTPError, OSError, ValueError) as exc:
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
                    self._validate_url(current_url)
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

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise BadRequestError("URL intake only supports http or https URLs.")
        if not parsed.hostname:
            raise BadRequestError("URL intake requires a hostname.")
        if parsed.username is not None or parsed.password is not None:
            raise BadRequestError("URL intake rejects user information in URLs.")
        if self._allow_private_addresses:
            return
        try:
            ip_address(parsed.hostname)
        except ValueError:
            return
        if not is_public_intake_address(parsed.hostname):
            raise BadRequestError("URL intake rejects private or local network targets.")
