import json

import httpx
import pytest

from flint_graph.application.embeddings import (
    EmbeddingBatchRequest,
    EmbeddingInput,
    EmbeddingModel,
)
from flint_graph.config import Settings
from flint_graph.infrastructure.embedding_factory import create_embedding_model
from flint_graph.infrastructure.embeddings import OpenAICompatibleEmbeddingModel
from flint_graph.infrastructure.ollama import OllamaEmbeddingModel


def test_embedding_factory_builds_ollama_model_in_local_env() -> None:
    settings = Settings(_env_file=None, env="local", anthropic_api_key="sk-test")

    model = create_embedding_model(settings, http_client=httpx.AsyncClient())

    assert isinstance(model, OllamaEmbeddingModel)


def test_embedding_factory_builds_openai_model_in_production_env() -> None:
    settings = Settings(
        _env_file=None,
        env="production",
        anthropic_api_key="sk-test",
        embedding_openai_api_key="sk-emb",
    )

    model = create_embedding_model(settings, http_client=httpx.AsyncClient())

    assert isinstance(model, OpenAICompatibleEmbeddingModel)


@pytest.mark.anyio
async def test_ollama_embedding_model_returns_validated_batch() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]},
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://ollama") as http_client:
        model: EmbeddingModel = OllamaEmbeddingModel(
            http_client=http_client,
            model="nomic-embed-text",
            timeout_seconds=12,
        )

        batch = await model.embed_batch(
            EmbeddingBatchRequest(
                provider="ollama",
                model="nomic-embed-text",
                dimensions=3,
                inputs=[
                    EmbeddingInput(input_id="chunk-000001", text="Acme"),
                    EmbeddingInput(input_id="chunk-000002", text="Berlin"),
                ],
            )
        )

    assert batch.provider == "ollama"
    assert batch.model == "nomic-embed-text"
    assert [item.vector for item in batch.embeddings] == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert batch.metadata["response_model"] == "nomic-embed-text"
    assert requests[0].url.path == "/api/embed"
    payload = json.loads(requests[0].read().decode("utf-8"))
    assert payload == {"model": "nomic-embed-text", "input": ["Acme", "Berlin"]}


@pytest.mark.anyio
async def test_openai_compatible_embedding_model_sends_bearer_token_and_dimensions() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "model": "text-embedding-3-small",
                "data": [
                    {"index": 0, "embedding": [0.1, 0.2]},
                    {"index": 1, "embedding": [0.3, 0.4]},
                ],
                "usage": {"prompt_tokens": 7, "total_tokens": 7},
            },
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://provider") as http_client:
        model = OpenAICompatibleEmbeddingModel(
            http_client=http_client,
            model="text-embedding-3-small",
            api_key="secret",
            timeout_seconds=20,
        )

        batch = await model.embed_batch(
            EmbeddingBatchRequest(
                provider="openai_compatible",
                model="text-embedding-3-small",
                dimensions=2,
                inputs=[
                    EmbeddingInput(input_id="chunk-000001", text="Acme"),
                    EmbeddingInput(input_id="chunk-000002", text="Berlin"),
                ],
            )
        )

    assert [item.input_id for item in batch.embeddings] == ["chunk-000001", "chunk-000002"]
    assert [item.vector for item in batch.embeddings] == [[0.1, 0.2], [0.3, 0.4]]
    assert batch.metadata["usage"] == {"prompt_tokens": 7, "total_tokens": 7}
    assert requests[0].headers["authorization"] == "Bearer secret"
    payload = json.loads(requests[0].read().decode("utf-8"))
    assert payload == {
        "model": "text-embedding-3-small",
        "input": ["Acme", "Berlin"],
        "dimensions": 2,
    }


@pytest.mark.anyio
async def test_embedding_adapters_reject_wrong_vector_count() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2]]}, request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://ollama") as http_client:
        model = OllamaEmbeddingModel(
            http_client=http_client,
            model="nomic-embed-text",
            timeout_seconds=12,
        )

        with pytest.raises(ValueError, match="returned 1 embeddings for 2 inputs"):
            await model.embed_batch(
                EmbeddingBatchRequest(
                    provider="ollama",
                    model="nomic-embed-text",
                    dimensions=2,
                    inputs=[
                        EmbeddingInput(input_id="chunk-000001", text="Acme"),
                        EmbeddingInput(input_id="chunk-000002", text="Berlin"),
                    ],
                )
            )
