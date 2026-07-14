from __future__ import annotations

import json
from hashlib import sha256
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

EmbeddingProvider = Literal["deterministic", "ollama", "openai_compatible"]
EMBEDDING_CONTRACT_VERSION: Literal["1"] = "1"


class EmbeddingInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EmbeddingBatchRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    contract_version: Literal["1"] = EMBEDDING_CONTRACT_VERSION
    provider: EmbeddingProvider
    model: str = Field(min_length=1, max_length=200)
    dimensions: int = Field(ge=1)
    inputs: list[EmbeddingInput] = Field(min_length=1)
    max_batch_size: int = Field(default=100, ge=1)
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_batch(self) -> EmbeddingBatchRequest:
        if len(self.inputs) > self.max_batch_size:
            raise ValueError("batch size exceeds max_batch_size")
        seen: set[str] = set()
        for item in self.inputs:
            if item.input_id in seen:
                raise ValueError(f"duplicate input id '{item.input_id}'")
            seen.add(item.input_id)
        return self


class EmbeddingVector(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_id: str = Field(min_length=1, max_length=200)
    vector: list[float] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EmbeddingBatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    contract_version: Literal["1"] = EMBEDDING_CONTRACT_VERSION
    provider: EmbeddingProvider
    model: str = Field(min_length=1, max_length=200)
    dimensions: int = Field(ge=1)
    embeddings: list[EmbeddingVector] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_dimensions(self) -> EmbeddingBatchResult:
        for item in self.embeddings:
            if len(item.vector) != self.dimensions:
                raise ValueError(
                    f"embedding '{item.input_id}' has dimension {len(item.vector)}, "
                    f"expected {self.dimensions}"
                )
        return self


class EmbeddingModel(Protocol):
    async def embed_batch(self, request: EmbeddingBatchRequest) -> EmbeddingBatchResult: ...


class DeterministicEmbeddingModel:
    async def embed_batch(self, request: EmbeddingBatchRequest) -> EmbeddingBatchResult:
        return EmbeddingBatchResult(
            provider=request.provider,
            model=request.model,
            dimensions=request.dimensions,
            embeddings=[
                EmbeddingVector(
                    input_id=item.input_id,
                    vector=_deterministic_vector(item.text, request.dimensions),
                )
                for item in request.inputs
            ],
            metadata={"algorithm": "sha256-repeated-bytes"},
        )


def embedding_config_hash(
    *,
    provider: EmbeddingProvider,
    model: str,
    dimensions: int,
    config: dict[str, Any] | None = None,
) -> str:
    payload = {
        "contract_version": EMBEDDING_CONTRACT_VERSION,
        "provider": provider,
        "model": model,
        "dimensions": dimensions,
        "config": config or {},
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


def _deterministic_vector(text: str, dimensions: int) -> list[float]:
    values: list[float] = []
    counter = 0
    while len(values) < dimensions:
        digest = sha256(f"{counter}:{text}".encode()).digest()
        values.extend((byte / 127.5) - 1.0 for byte in digest)
        counter += 1
    return values[:dimensions]
