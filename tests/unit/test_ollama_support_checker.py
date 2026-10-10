import json
from uuid import uuid4

import httpx
import pytest

from flint_graph.application.query_orchestration import (
    PackedContextRecord,
    QueryContextPack,
    SupportCheckClaim,
    SupportCheckRequest,
)
from flint_graph.infrastructure import ollama


def _checker_cls() -> type:
    return ollama.OllamaSupportChecker


def _support_method() -> str:
    return ollama.OLLAMA_SUPPORT_METHOD


def _support_request() -> SupportCheckRequest:
    return SupportCheckRequest(
        tenant_id=uuid4(),
        query="Where is Acme Corporation headquartered?",
        context_pack=QueryContextPack(
            pack_id="pack-1",
            token_budget=100,
            records=[
                PackedContextRecord(
                    context_id="ctx-0001",
                    candidate_id="lexical:chunk:chunk-acme",
                    citation_id="c1",
                    text="Acme Corporation is headquartered in Berlin.",
                    token_count=6,
                    source_ids={"chunk_id": "chunk-acme"},
                ),
            ],
        ),
        claims=[
            SupportCheckClaim(
                claim_index=0,
                text="Acme Corporation is headquartered in Berlin.",
                citation_ids=["c1"],
            ),
            SupportCheckClaim(
                claim_index=1,
                text="Acme was founded in 1901.",
                citation_ids=["c1"],
            ),
        ],
    )


@pytest.mark.anyio
async def test_ollama_support_checker_sends_schema_and_maps_judgements() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "model": "llama3.2",
                "response": json.dumps(
                    {
                        "judgements": [
                                {
                                    "claim_index": 0,
                                    "support_status": "supported",
                                    "support_score": 0.95,
                                    "reason": "context states the Berlin headquarters",
                                },
                                {
                                    "claim_index": 1,
                                    "support_status": "unsupported",
                                    "support_score": 0.1,
                                    "reason": "founding year is not in the context",
                                },
                        ]
                    }
                ),
            },
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://ollama") as http_client:
        checker = _checker_cls()(
            model="llama3.2",
            timeout_seconds=12,
            temperature=0.0,
            max_tokens=256,
            http_client=http_client,
        )

        result = await checker.check(_support_request())

    assert result.method == _support_method()
    assert result.metadata["provider"] == "ollama"
    assert result.metadata["model"] == "llama3.2"
    # Usage accounting reads token counts from this metadata; the fake response
    # carries no eval counters, so only the measured duration is present.
    assert set(result.metadata["usage"]) <= {
        "duration_ms",
        "input_tokens",
        "output_tokens",
    }
    assert [claim.support_status for claim in result.claims] == ["supported", "unsupported"]
    assert result.claims[0].support_score == pytest.approx(0.95)
    assert result.claims[0].citation_ids == ["c1"]
    assert result.claims[1].support_reason == "founding year is not in the context"

    payload = json.loads(requests[0].content)
    assert requests[0].url.path == "/api/generate"
    assert payload["model"] == "llama3.2"
    assert payload["stream"] is False
    assert payload["format"]["properties"]["judgements"]["items"]["required"] == [
        "claim_index",
        "support_status",
        "support_score",
        "reason",
    ]
    assert "claim_index 0" in payload["prompt"]
    assert "cited context: Acme Corporation is headquartered in Berlin." in payload["prompt"]
    assert "Missing information is not evidence" in payload["prompt"]
    assert result.metadata["support_prompt_version"] == "grounded-support-v3"
    judgements = payload["format"]["properties"]["judgements"]
    assert judgements["minItems"] == judgements["maxItems"] == 2
    assert judgements["items"]["properties"]["claim_index"]["enum"] == [0, 1]
    assert "Do not judge a premise by whether it answers the whole query" in payload["prompt"]


@pytest.mark.anyio
async def test_ollama_support_checker_defaults_missing_judgement_to_unsupported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "response": json.dumps(
                    {
                        "judgements": [
                            {
                                "claim_index": 0,
                                "support_status": "supported",
                                "support_score": 0.9,
                                "reason": "ok",
                            }
                        ]
                    }
                )
            },
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://ollama") as http_client:
        checker = _checker_cls()(
            model="llama3.2",
            timeout_seconds=12,
            temperature=0.0,
            max_tokens=256,
            http_client=http_client,
        )

        result = await checker.check(_support_request())

    assert result.claims[1].support_status == "unsupported"
    assert result.claims[1].support_score == 0.0
    assert result.claims[1].support_reason == "no judgement returned for this claim"


@pytest.mark.anyio
async def test_ollama_support_checker_coerces_status_and_clamps_score() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "response": json.dumps(
                    {
                        "judgements": [
                            {
                                "claim_index": 0,
                                "support_status": "SUPPORTED",
                                "support_score": 1.5,
                                "reason": "x",
                            },
                            {
                                "claim_index": 1,
                                "support_status": "maybe",
                                "support_score": -0.2,
                                "reason": "y",
                            },
                        ]
                    }
                )
            },
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://ollama") as http_client:
        checker = _checker_cls()(
            model="llama3.2",
            timeout_seconds=12,
            temperature=0.0,
            max_tokens=256,
            http_client=http_client,
        )

        result = await checker.check(_support_request())

    assert result.claims[0].support_status == "supported"
    assert result.claims[0].support_score == 1.0
    assert result.claims[1].support_status == "unsupported"
    assert result.claims[1].support_score == 0.0


@pytest.mark.anyio
async def test_ollama_support_checker_skips_model_call_with_no_claims() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500, request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://ollama") as http_client:
        checker = _checker_cls()(
            model="llama3.2",
            timeout_seconds=12,
            temperature=0.0,
            max_tokens=256,
            http_client=http_client,
        )
        request = _support_request().model_copy(update={"claims": []})

        result = await checker.check(request)

    assert result.claims == []
    assert result.method == _support_method()
    assert requests == []


@pytest.mark.anyio
async def test_ollama_support_checker_rejects_malformed_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"response": '{"judgements":"not a list"}'},
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://ollama") as http_client:
        checker = _checker_cls()(
            model="llama3.2",
            timeout_seconds=12,
            temperature=0.0,
            max_tokens=256,
            http_client=http_client,
        )

        with pytest.raises(ValueError, match="Ollama support response did not match"):
            await checker.check(_support_request())


@pytest.mark.anyio
async def test_duplicate_support_judgements_are_not_selected_by_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": json.dumps({"judgements": [
            {"claim_index": 0, "support_status": "unsupported", "support_score": 0,
             "reason": "no"},
            {"claim_index": 0, "support_status": "supported", "support_score": 1,
             "reason": "yes"},
        ]})}, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://ollama"
    ) as client:
        checker = _checker_cls()(model="fixture", timeout_seconds=12, temperature=0,
                                 max_tokens=256, http_client=client)
        result = await checker.check(_support_request())
    assert result.claims[0].support_status == "unsupported"
    assert result.claims[0].support_reason == "duplicate judgements returned for this claim"
