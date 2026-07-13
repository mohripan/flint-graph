from __future__ import annotations

import httpx


class OllamaExtractionClient:
    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        base_url: str | None = None,
    ) -> None:
        self._http_client = http_client or httpx.AsyncClient(
            base_url=base_url or "http://localhost:11434"
        )

    async def extract(
        self,
        *,
        prompt: str,
        model: str,
        timeout_seconds: int,
    ) -> str:
        response = await self._http_client.post(
            "/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        response_text = payload.get("response")
        if not isinstance(response_text, str):
            raise ValueError("Ollama response did not include a string 'response' field.")
        return response_text
