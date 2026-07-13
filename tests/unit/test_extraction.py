import json

import httpx
import pytest

from atlas_rag.application.extraction import (
    ExtractionValidationError,
    build_extraction_prompt,
    parse_extraction_response,
)
from atlas_rag.infrastructure.ollama import OllamaExtractionClient


def test_parse_extraction_response_validates_builtin_schema() -> None:
    payload = json.dumps(
        {
            "title": "Atlas",
            "summary": "AtlasRAG stores source content and derives chunks.",
            "topics": ["content pipeline", "lineage"],
            "entities": [
                {"name": "AtlasRAG", "type": "concept"},
                {"name": "OpenAI", "type": "organization"},
            ],
        }
    )

    extraction = parse_extraction_response(payload)

    assert extraction.title == "Atlas"
    assert extraction.summary == "AtlasRAG stores source content and derives chunks."
    assert extraction.topics == ["content pipeline", "lineage"]
    assert extraction.entities[1].type == "organization"


def test_parse_extraction_response_rejects_invalid_llm_json() -> None:
    with pytest.raises(ExtractionValidationError, match="valid JSON"):
        parse_extraction_response("not json")

    with pytest.raises(ExtractionValidationError, match="summary"):
        parse_extraction_response(json.dumps({"title": "Atlas"}))


def test_parse_extraction_response_parses_claim_triples() -> None:
    payload = json.dumps(
        {
            "summary": "Acme Corp is headquartered in Berlin.",
            "entities": [
                {"name": "Acme Corp", "type": "organization"},
                {"name": "Berlin", "type": "place"},
            ],
            "claims": [
                {
                    "subject": "Acme Corp",
                    "predicate": "headquartered_in",
                    "object": "Berlin",
                    "evidence_chunk_ids": ["chunk-000001"],
                }
            ],
        }
    )

    extraction = parse_extraction_response(payload)

    assert len(extraction.claims) == 1
    claim = extraction.claims[0]
    assert claim.subject == "Acme Corp"
    assert claim.predicate == "headquartered_in"
    assert claim.object == "Berlin"
    assert claim.evidence_chunk_ids == ["chunk-000001"]


def test_parse_extraction_response_v1_without_claims_is_backward_compatible() -> None:
    payload = json.dumps(
        {
            "title": "Atlas",
            "summary": "AtlasRAG stores source content and derives chunks.",
            "topics": ["content pipeline"],
            "entities": [{"name": "AtlasRAG", "type": "concept"}],
        }
    )

    extraction = parse_extraction_response(payload)

    assert extraction.claims == []
    assert extraction.entities[0].name == "AtlasRAG"


def test_parse_extraction_response_rejects_malformed_claim() -> None:
    payload = json.dumps(
        {
            "summary": "A claim with an empty predicate is invalid.",
            "claims": [{"subject": "Acme Corp", "predicate": "", "object": "Berlin"}],
        }
    )

    with pytest.raises(ExtractionValidationError, match="predicate"):
        parse_extraction_response(payload)


def test_build_extraction_prompt_includes_claim_schema() -> None:
    prompt = build_extraction_prompt([("chunk-000001", "Acme Corp is in Berlin.")])

    assert '"subject": "string"' in prompt
    assert '"predicate": "string"' in prompt
    assert '"evidence_chunk_ids"' in prompt


def test_build_extraction_prompt_is_deterministic_and_contains_schema() -> None:
    chunks = [
        ("chunk-000001", "AtlasRAG stores content."),
        ("chunk-000002", "Chunks preserve lineage."),
    ]

    first = build_extraction_prompt(chunks)
    second = build_extraction_prompt(chunks)

    assert first == second
    assert '"summary": "string"' in first
    assert "[chunk-000001]\nAtlasRAG stores content." in first
    assert "[chunk-000002]\nChunks preserve lineage." in first


@pytest.mark.anyio
async def test_ollama_extraction_client_returns_generate_response_text() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"response": '{"summary":"ok"}'})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://ollama") as http_client:
        client = OllamaExtractionClient(http_client=http_client)

        response = await client.extract(
            prompt="Extract facts",
            model="gemma3:1b",
            timeout_seconds=30,
        )

    assert response == '{"summary":"ok"}'
    assert requests[0].url.path == "/api/generate"
    assert json.loads(requests[0].content) == {
        "model": "gemma3:1b",
        "prompt": "Extract facts",
        "stream": False,
        "format": "json",
    }
