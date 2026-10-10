import json
from uuid import uuid4

import httpx
import pytest

from flint_graph.application.query_orchestration import (
    AnswerGenerationRequest,
    PackedContextRecord,
    QueryContextPack,
    StreamingAnswerGenerator,
    SupportCheckClaim,
    SupportCheckRequest,
)
from flint_graph.config import Settings
from flint_graph.infrastructure.answer_generator_factory import (
    create_answer_generator,
    create_support_checker,
)


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["answer", "stream", "support"])
async def test_configured_ollama_context_is_sent_without_changing_output_budget(
    operation: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["options"] == {
            "temperature": 0.0,
            "num_predict": 256,
            "num_ctx": 16384,
        }
        draft = (
            {"insufficient_context": True, "claims": []}
            if operation != "support"
            else {
                "judgements": [
                    {
                        "claim_index": 0,
                        "support_status": "supported",
                        "support_score": 1.0,
                        "reason": "explicit source",
                    }
                ]
            }
        )
        response = {"response": json.dumps(draft), "done": True}
        if payload["stream"]:
            return httpx.Response(200, content=json.dumps(response))
        return httpx.Response(200, json=response)

    settings = Settings(
        _env_file=None,
        env="test",
        query_answer_provider="ollama",
        query_support_provider="ollama",
        query_answer_max_tokens=256,
        query_ollama_context_tokens=16384,
    )
    request = AnswerGenerationRequest(
        tenant_id=uuid4(),
        query="Where is Acme headquartered?",
        retrieval_index_version_id=uuid4(),
        context_pack=QueryContextPack(
            pack_id="context-fixture",
            token_budget=100,
            records=[
                PackedContextRecord(
                    context_id="context-1",
                    candidate_id="lexical:chunk:1",
                    citation_id="c1",
                    text="Acme is headquartered in Berlin.",
                    token_count=6,
                    source_ids={"chunk_id": "fixture-1"},
                )
            ],
        ),
    )
    async with httpx.AsyncClient(
        base_url="http://ollama", transport=httpx.MockTransport(handler)
    ) as client:
        if operation == "support":
            result = await create_support_checker(settings, http_client=client).check(
                SupportCheckRequest(
                    tenant_id=request.tenant_id,
                    query=request.query,
                    context_pack=request.context_pack,
                    claims=[
                        SupportCheckClaim(
                            claim_index=0,
                            text="Acme is headquartered in Berlin.",
                            citation_ids=["c1"],
                        )
                    ],
                )
            )
            assert result.claims[0].support_status == "supported"
        else:
            generator = create_answer_generator(settings, http_client=client)
            if operation == "stream":
                assert isinstance(generator, StreamingAnswerGenerator)

                async def on_delta(text: str) -> None:
                    pass

                answer = await generator.stream_generate(request, on_delta)
            else:
                answer = await generator.generate(request)
            assert answer.insufficient_context is True
