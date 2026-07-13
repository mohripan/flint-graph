import json

import httpx
import pytest
from pydantic import ValidationError

from atlas_rag.application.extraction_proposals import (
    DeterministicExtractionModel,
    EvidenceProposal,
    ExtractedClaimProposal,
    ExtractedEntityProposal,
    ExtractedRelationProposal,
    ExtractionBatch,
    ExtractionBatchRequest,
    ExtractionInputChunk,
    StructuredExtractionModel,
)
from atlas_rag.infrastructure.ollama import OllamaProposalExtractionModel


def _evidence(chunk_id: str = "chunk-000001") -> list[EvidenceProposal]:
    return [EvidenceProposal(chunk_id=chunk_id, quote="Acme Corporation")]


def test_extraction_batch_rejects_duplicate_local_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate local id"):
        ExtractionBatch(
            input_chunk_ids=["chunk-000001"],
            entities=[
                ExtractedEntityProposal(
                    local_id="e1",
                    name="Acme Corporation",
                    entity_type="organization",
                    evidence=_evidence(),
                ),
                ExtractedEntityProposal(
                    local_id="e1",
                    name="Acme Corp",
                    entity_type="organization",
                    evidence=_evidence(),
                ),
            ],
        )


def test_extraction_batch_rejects_unknown_relation_references() -> None:
    with pytest.raises(ValidationError, match="unknown entity reference"):
        ExtractionBatch(
            input_chunk_ids=["chunk-000001"],
            entities=[
                ExtractedEntityProposal(
                    local_id="e1",
                    name="Acme Corporation",
                    entity_type="organization",
                    evidence=_evidence(),
                )
            ],
            relations=[
                ExtractedRelationProposal(
                    local_id="r1",
                    subject_entity_id="e1",
                    predicate="headquartered_in",
                    object_entity_id="e2",
                    evidence=[EvidenceProposal(chunk_id="chunk-000001", quote="Berlin")],
                )
            ],
        )


def test_extraction_batch_rejects_evidence_outside_invocation_input() -> None:
    with pytest.raises(ValidationError, match="outside invocation input"):
        ExtractionBatch(
            input_chunk_ids=["chunk-000001"],
            entities=[
                ExtractedEntityProposal(
                    local_id="e1",
                    name="Acme Corporation",
                    entity_type="organization",
                    evidence=_evidence("chunk-000999"),
                )
            ],
        )


def test_relation_rejects_self_reference_and_malformed_predicate() -> None:
    with pytest.raises(ValidationError, match="self-referential relation"):
        ExtractedRelationProposal(
            local_id="r1",
            subject_entity_id="e1",
            predicate="headquartered_in",
            object_entity_id="e1",
            evidence=_evidence(),
        )

    with pytest.raises(ValidationError, match="malformed predicate"):
        ExtractedRelationProposal(
            local_id="r1",
            subject_entity_id="e1",
            predicate="headquartered in",
            object_entity_id="e2",
            evidence=_evidence(),
        )


def test_claim_requires_exactly_one_object_form() -> None:
    with pytest.raises(ValidationError, match="exactly one object"):
        ExtractedClaimProposal(
            local_id="c1",
            subject_entity_id="e1",
            predicate="founded",
            evidence=_evidence(),
        )

    with pytest.raises(ValidationError, match="exactly one object"):
        ExtractedClaimProposal(
            local_id="c1",
            subject_entity_id="e1",
            predicate="founded",
            object_entity_id="e2",
            object_text="Berlin",
            evidence=_evidence(),
        )


@pytest.mark.anyio
async def test_deterministic_extraction_model_extracts_capitalized_entity_proposals() -> None:
    model: StructuredExtractionModel = DeterministicExtractionModel()

    batch = await model.extract_batch(
        ExtractionBatchRequest(
            chunks=[
                ExtractionInputChunk(
                    chunk_id="chunk-000001",
                    text="Acme Corporation is headquartered in Berlin.",
                )
            ]
        )
    )

    assert batch.input_chunk_ids == ["chunk-000001"]
    assert [(entity.local_id, entity.name) for entity in batch.entities] == [
        ("e1", "Acme Corporation"),
        ("e2", "Berlin"),
    ]
    assert batch.entities[0].entity_type == "other"
    assert batch.entities[0].evidence == [
        EvidenceProposal(
            chunk_id="chunk-000001", quote="Acme Corporation", start_hint=0
        )
    ]


@pytest.mark.anyio
async def test_deterministic_extraction_model_deduplicates_entities_across_chunks() -> None:
    model = DeterministicExtractionModel()

    batch = await model.extract_batch(
        ExtractionBatchRequest(
            chunks=[
                ExtractionInputChunk(chunk_id="chunk-000001", text="Acme Corporation ships."),
                ExtractionInputChunk(chunk_id="chunk-000002", text="Acme Corporation grows."),
            ]
        )
    )

    assert [entity.name for entity in batch.entities] == ["Acme Corporation"]
    assert batch.entities[0].evidence == [
        EvidenceProposal(
            chunk_id="chunk-000001", quote="Acme Corporation", start_hint=0
        ),
        EvidenceProposal(
            chunk_id="chunk-000002", quote="Acme Corporation", start_hint=0
        ),
    ]


@pytest.mark.anyio
async def test_deterministic_extraction_model_adds_start_hint_for_repeated_quote() -> None:
    model = DeterministicExtractionModel()

    batch = await model.extract_batch(
        ExtractionBatchRequest(
            chunks=[
                ExtractionInputChunk(
                    chunk_id="chunk-000001",
                    text="Acme Corporation acquired Acme Corporation.",
                )
            ]
        )
    )

    entity = next(entity for entity in batch.entities if entity.name == "Acme Corporation")
    assert [evidence.start_hint for evidence in entity.evidence] == [0, 26]


@pytest.mark.anyio
async def test_ollama_proposal_extraction_model_returns_validated_batch() -> None:
    requests: list[httpx.Request] = []
    response_batch = ExtractionBatch(
        input_chunk_ids=["chunk-000001"],
        entities=[
            ExtractedEntityProposal(
                local_id="e1",
                name="Acme Corporation",
                entity_type="organization",
                evidence=[EvidenceProposal(chunk_id="chunk-000001", quote="Acme Corporation")],
            )
        ],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"response": response_batch.model_dump_json()})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://ollama") as http_client:
        model: StructuredExtractionModel = OllamaProposalExtractionModel(
            http_client=http_client,
            model="llama3.2",
            timeout_seconds=45,
        )

        batch = await model.extract_batch(
            ExtractionBatchRequest(
                chunks=[
                    ExtractionInputChunk(
                        chunk_id="chunk-000001",
                        text="Acme Corporation is headquartered in Berlin.",
                    )
                ]
            )
        )

    assert batch == response_batch
    assert requests[0].url.path == "/api/generate"
    request_payload = json.loads(requests[0].read().decode("utf-8"))
    assert request_payload["model"] == "llama3.2"
    assert request_payload["format"]["type"] == "object"
    assert request_payload["format"]["properties"]["entities"]["items"]["properties"][
        "entity_type"
    ]["enum"] == ["person", "organization", "place", "concept", "other"]
    assert request_payload["options"] == {"temperature": 0}
    assert "Acme Corporation is headquartered in Berlin." in request_payload["prompt"]


@pytest.mark.anyio
async def test_ollama_proposal_extraction_model_includes_error_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, request=request, text="schema rejected")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://ollama") as http_client:
        model = OllamaProposalExtractionModel(
            http_client=http_client,
            model="llama3.2",
            timeout_seconds=45,
        )

        with pytest.raises(httpx.HTTPStatusError, match="schema rejected"):
            await model.extract_batch(
                ExtractionBatchRequest(
                    chunks=[
                        ExtractionInputChunk(
                            chunk_id="chunk-000001",
                            text="Acme Corporation is headquartered in Berlin.",
                        )
                    ]
                )
            )
