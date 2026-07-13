from __future__ import annotations

import json

import httpx

from atlas_rag.application.extraction_proposals import ExtractionBatch, ExtractionBatchRequest


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


class OllamaProposalExtractionModel:
    def __init__(
        self,
        *,
        model: str,
        timeout_seconds: int,
        http_client: httpx.AsyncClient | None = None,
        base_url: str | None = None,
    ) -> None:
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client or httpx.AsyncClient(
            base_url=base_url or "http://localhost:11434"
        )

    async def extract_batch(self, request: ExtractionBatchRequest) -> ExtractionBatch:
        response = await self._http_client.post(
            "/api/generate",
            json={
                "model": self._model,
                "prompt": _build_proposal_extraction_prompt(request),
                "stream": False,
                "format": "json",
            },
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        response_text = payload.get("response")
        if not isinstance(response_text, str):
            raise ValueError("Ollama response did not include a string 'response' field.")
        return ExtractionBatch.model_validate_json(response_text)


def _build_proposal_extraction_prompt(request: ExtractionBatchRequest) -> str:
    schema = ExtractionBatch.model_json_schema()
    chunks = "\n\n".join(f"[{chunk.chunk_id}]\n{chunk.text}" for chunk in request.chunks)
    return "\n".join(
        [
            "Extract evidence-backed knowledge proposals from the document chunks.",
            "Return only JSON matching this schema:",
            json.dumps(schema, indent=2, sort_keys=True),
            "Rules:",
            "- Use only chunk IDs from input_chunk_ids.",
            "- Evidence quotes must be exact substrings from the referenced chunk.",
            "- Use batch-local entity IDs for relation and claim references.",
            "- Do not include canonical entity IDs.",
            "Document chunks:",
            chunks,
        ]
    )
