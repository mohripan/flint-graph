from __future__ import annotations

from typing import Any

import httpx

from atlas_rag.application.embeddings import (
    EmbeddingBatchRequest,
    EmbeddingBatchResult,
    EmbeddingVector,
)
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
        _raise_for_status(response)
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
                "format": _proposal_extraction_schema(),
                "options": {"temperature": 0},
            },
            timeout=self._timeout_seconds,
        )
        _raise_for_status(response)
        payload = response.json()
        response_text = payload.get("response")
        if not isinstance(response_text, str):
            raise ValueError("Ollama response did not include a string 'response' field.")
        return ExtractionBatch.model_validate_json(response_text)


class OllamaEmbeddingModel:
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

    async def embed_batch(self, request: EmbeddingBatchRequest) -> EmbeddingBatchResult:
        response = await self._http_client.post(
            "/api/embed",
            json={
                "model": self._model,
                "input": [item.text for item in request.inputs],
            },
            timeout=self._timeout_seconds,
        )
        _raise_for_status(response)
        payload = response.json()
        embeddings = payload.get("embeddings")
        if not isinstance(embeddings, list):
            raise ValueError("Ollama response did not include a list 'embeddings' field.")
        if len(embeddings) != len(request.inputs):
            raise ValueError(
                f"Ollama returned {len(embeddings)} embeddings for {len(request.inputs)} inputs"
            )

        return EmbeddingBatchResult(
            provider=request.provider,
            model=request.model,
            dimensions=request.dimensions,
            embeddings=[
                EmbeddingVector(
                    input_id=item.input_id,
                    vector=_parse_vector(vector),
                )
                for item, vector in zip(request.inputs, embeddings, strict=True)
            ],
            metadata={"response_model": payload.get("model", self._model)},
        )


def _build_proposal_extraction_prompt(request: ExtractionBatchRequest) -> str:
    chunks = "\n\n".join(f"[{chunk.chunk_id}]\n{chunk.text}" for chunk in request.chunks)
    return "\n".join(
        [
            "Extract evidence-backed knowledge proposals from the document chunks.",
            "Return only JSON that satisfies the response schema supplied in the format parameter.",
            "Rules:",
            "- Use only chunk IDs from input_chunk_ids.",
            "- Include input_chunk_ids exactly as supplied below.",
            "- Entity type must be exactly one of: person, organization, place, concept, other.",
            "- Evidence quotes must be exact substrings from the referenced chunk.",
            "- Every entity, relation, and claim must include at least one evidence item.",
            "- Use batch-local entity IDs for relation and claim references.",
            "- Do not include canonical entity IDs.",
            "- Prefer empty arrays when the text does not support a proposal.",
            "Example output shape:",
            (
                '{"input_chunk_ids":["chunk-000001"],"entities":[{"local_id":"e1",'
                '"name":"Acme Corporation","entity_type":"organization","evidence":'
                '[{"chunk_id":"chunk-000001","quote":"Acme Corporation"}]}],'
                '"relations":[],"claims":[]}'
            ),
            "Document chunks:",
            chunks,
        ]
    )


def _proposal_extraction_schema() -> dict[str, Any]:
    evidence_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "chunk_id": {"type": "string"},
            "quote": {"type": "string"},
            "start_hint": {"type": "integer"},
        },
        "required": ["chunk_id", "quote"],
    }
    return {
        "type": "object",
        "properties": {
            "input_chunk_ids": {"type": "array", "items": {"type": "string"}},
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "local_id": {"type": "string"},
                        "name": {"type": "string"},
                        "entity_type": {
                            "type": "string",
                            "enum": [
                                "person",
                                "organization",
                                "place",
                                "concept",
                                "other",
                            ],
                        },
                        "aliases": {"type": "array", "items": {"type": "string"}},
                        "confidence": {"type": "number"},
                        "evidence": {
                            "type": "array",
                            "minItems": 1,
                            "items": evidence_schema,
                        },
                    },
                    "required": ["local_id", "name", "entity_type", "evidence"],
                },
            },
            "relations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "local_id": {"type": "string"},
                        "subject_entity_id": {"type": "string"},
                        "predicate": {"type": "string"},
                        "object_entity_id": {"type": "string"},
                        "confidence": {"type": "number"},
                        "evidence": {
                            "type": "array",
                            "minItems": 1,
                            "items": evidence_schema,
                        },
                    },
                    "required": [
                        "local_id",
                        "subject_entity_id",
                        "predicate",
                        "object_entity_id",
                        "evidence",
                    ],
                },
            },
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "local_id": {"type": "string"},
                        "subject_entity_id": {"type": "string"},
                        "predicate": {"type": "string"},
                        "object_entity_id": {"type": "string"},
                        "object_text": {"type": "string"},
                        "confidence": {"type": "number"},
                        "evidence": {
                            "type": "array",
                            "minItems": 1,
                            "items": evidence_schema,
                        },
                    },
                    "required": ["local_id", "predicate", "evidence"],
                },
            },
        },
        "required": ["input_chunk_ids", "entities", "relations", "claims"],
    }


def _parse_vector(value: Any) -> list[float]:
    if not isinstance(value, list) or not all(isinstance(item, int | float) for item in value):
        raise ValueError("embedding vector must be a list of numbers.")
    return [float(item) for item in value]


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    message = (
        f"{response.status_code} {response.reason_phrase} from Ollama: "
        f"{response.text[:500]}"
    )
    raise httpx.HTTPStatusError(message, request=response.request, response=response)
