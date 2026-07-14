import pytest
from pydantic import ValidationError

from atlas_rag.application.embeddings import (
    DeterministicEmbeddingModel,
    EmbeddingBatchRequest,
    EmbeddingInput,
    embedding_config_hash,
)


def test_embedding_batch_request_rejects_duplicate_input_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate input id"):
        EmbeddingBatchRequest(
            provider="deterministic",
            model="deterministic-test",
            dimensions=4,
            inputs=[
                EmbeddingInput(input_id="chunk-000001", text="Acme"),
                EmbeddingInput(input_id="chunk-000001", text="Berlin"),
            ],
        )


def test_embedding_batch_request_rejects_batch_larger_than_limit() -> None:
    with pytest.raises(ValidationError, match="batch size exceeds"):
        EmbeddingBatchRequest(
            provider="deterministic",
            model="deterministic-test",
            dimensions=4,
            max_batch_size=1,
            inputs=[
                EmbeddingInput(input_id="chunk-000001", text="Acme"),
                EmbeddingInput(input_id="chunk-000002", text="Berlin"),
            ],
        )


@pytest.mark.anyio
async def test_deterministic_embedding_model_returns_stable_unit_length_vectors() -> None:
    model = DeterministicEmbeddingModel()
    request = EmbeddingBatchRequest(
        provider="deterministic",
        model="deterministic-test",
        dimensions=6,
        inputs=[
            EmbeddingInput(input_id="chunk-000001", text="Acme Corporation"),
            EmbeddingInput(input_id="chunk-000002", text="Acme Corporation"),
        ],
    )

    first = await model.embed_batch(request)
    second = await model.embed_batch(request)

    assert first.provider == "deterministic"
    assert first.model == "deterministic-test"
    assert [item.input_id for item in first.embeddings] == ["chunk-000001", "chunk-000002"]
    assert [len(item.vector) for item in first.embeddings] == [6, 6]
    assert first.embeddings[0].vector == first.embeddings[1].vector
    assert first == second
    assert all(-1.0 <= value <= 1.0 for item in first.embeddings for value in item.vector)


def test_embedding_config_hash_is_stable_and_ignores_key_order() -> None:
    first = embedding_config_hash(
        provider="ollama",
        model="nomic-embed-text",
        dimensions=768,
        config={"truncate": True, "options": {"temperature": 0, "top_k": 10}},
    )
    second = embedding_config_hash(
        provider="ollama",
        model="nomic-embed-text",
        dimensions=768,
        config={"options": {"top_k": 10, "temperature": 0}, "truncate": True},
    )
    different = embedding_config_hash(
        provider="ollama",
        model="nomic-embed-text",
        dimensions=384,
        config={"truncate": True, "options": {"temperature": 0, "top_k": 10}},
    )

    assert first.startswith("sha256:")
    assert first == second
    assert first != different
