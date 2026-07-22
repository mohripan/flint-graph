from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

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
    def __init__(self, *, timeout_seconds: float, max_bytes: int) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes

    async def fetch(self, url: str) -> FetchedURL:
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=self._timeout_seconds,
            ) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
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
        except BadRequestError:
            raise
        except httpx.HTTPStatusError as exc:
            raise BadRequestError(
                f"URL returned an unsuccessful status: {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise BadRequestError("URL content could not be fetched.") from exc
