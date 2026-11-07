"""Seeing a picture for the assistant, whose own model may not be able to (ADR 0076).

The creator's chosen writing model stays as it is. A small vision model looks at the screenshot
and the assistant is told, in words, what it shows. Failures are reduced to a safe error, so
neither a provider's body nor a prompt reaches logs or stored state.
"""

from __future__ import annotations

import base64
from typing import Any, Protocol

import httpx

from flint_graph.config import Settings

# Enough to say what is on screen. The prompt asks for at most 120 words.
_MAX_TOKENS = 260
_TIMEOUT_SECONDS = 180.0


class ImageDescriptionError(Exception):
    """The picture could not be read. Carries no provider detail."""


class ImageDescriber(Protocol):
    async def describe(self, png: bytes, prompt: str) -> str: ...


class OllamaImageDescriber:
    def __init__(
        self,
        *,
        model: str,
        timeout_seconds: float = _TIMEOUT_SECONDS,
        http_client: httpx.AsyncClient | None = None,
        base_url: str | None = None,
    ) -> None:
        self._model, self._timeout = model, timeout_seconds
        self._client = http_client or httpx.AsyncClient(
            base_url=base_url or "http://localhost:11434"
        )

    async def describe(self, png: bytes, prompt: str) -> str:
        body: dict[str, Any] = {
            "model": self._model,
            "stream": False,
            # The image and voice workers share this GPU, so give the memory straight back.
            "keep_alive": 0,
            "think": False,
            "options": {"temperature": 0.1, "num_predict": _MAX_TOKENS},
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [base64.b64encode(png).decode("ascii")],
                }
            ],
        }
        try:
            response = await self._client.post("/api/chat", json=body, timeout=self._timeout)
            response.raise_for_status()
            content = response.json()["message"]["content"]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise ImageDescriptionError("unavailable") from None
        if not isinstance(content, str) or not content.strip():
            raise ImageDescriptionError("empty")
        return content.strip()


def build_image_describer(settings: Settings) -> ImageDescriber | None:
    """The configured vision model, or ``None`` when pictures are off."""
    model = settings.narrative_assistant_vision_model
    if not model:
        return None
    return OllamaImageDescriber(model=model, base_url=settings.ollama_base_url)
