from __future__ import annotations

from typing import Any

import httpx

from atlas_rag.application.embeddings import (
    EmbeddingBatchRequest,
    EmbeddingBatchResult,
    EmbeddingVector,
)


class OpenAICompatibleEmbeddingModel:
    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        timeout_seconds: int,
        http_client: httpx.AsyncClient | None = None,
        base_url: str | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client or httpx.AsyncClient(
            base_url=base_url or "https://api.openai.com"
        )

    async def embed_batch(self, request: EmbeddingBatchRequest) -> EmbeddingBatchResult:
        response = await self._http_client.post(
            "/v1/embeddings",
            json={
                "model": self._model,
                "input": [item.text for item in request.inputs],
                "dimensions": request.dimensions,
            },
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=self._timeout_seconds,
        )
        _raise_for_status(response, provider_name="OpenAI-compatible embedding provider")
        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError("embedding response did not include a list 'data' field.")

        vectors_by_index = _openai_vectors_by_index(data)
        if len(vectors_by_index) != len(request.inputs):
            raise ValueError(
                f"provider returned {len(vectors_by_index)} embeddings for "
                f"{len(request.inputs)} inputs"
            )

        return EmbeddingBatchResult(
            provider=request.provider,
            model=request.model,
            dimensions=request.dimensions,
            embeddings=[
                EmbeddingVector(
                    input_id=item.input_id,
                    vector=vectors_by_index[index],
                )
                for index, item in enumerate(request.inputs)
            ],
            metadata={
                "response_model": payload.get("model", self._model),
                "usage": payload.get("usage"),
            },
        )


def _openai_vectors_by_index(data: list[Any]) -> dict[int, list[float]]:
    vectors_by_index: dict[int, list[float]] = {}
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("embedding response item was not an object.")
        index = item.get("index")
        vector = item.get("embedding")
        if (
            not isinstance(index, int)
            or not isinstance(vector, list)
            or not all(isinstance(value, int | float) for value in vector)
        ):
            raise ValueError("embedding response item had invalid index or embedding.")
        vectors_by_index[index] = [float(value) for value in vector]
    return vectors_by_index


def _raise_for_status(response: httpx.Response, *, provider_name: str) -> None:
    if response.is_success:
        return
    message = (
        f"{response.status_code} {response.reason_phrase} from {provider_name}: "
        f"{response.text[:500]}"
    )
    raise httpx.HTTPStatusError(message, request=response.request, response=response)
