from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from flint_graph.evaluation.capture import CaptureManifest, capture_dataset
from flint_graph.evaluation.datasets import DatasetMetadata, GoldenDataset, GoldenQuery
from flint_graph.evaluation.recorded import load_recorded_evaluations


def _dataset() -> GoldenDataset:
    return GoldenDataset(
        metadata=DatasetMetadata(name="mini", version=1, tenant="test"),
        queries=[GoldenQuery(id="q1", query="Where?", query_type="factoid")],
    )


def _manifest() -> CaptureManifest:
    return CaptureManifest(
        tenant_id=UUID("11111111-1111-4111-8111-111111111111"),
        dataset_name="mini",
        dataset_version=1,
        document_labels={"doc-id": "doc-a"},
    )


class _ConversationAPI:
    """External HTTP fixture; capture still runs through its public interface."""

    def __init__(self):
        tenant = str(_manifest().tenant_id)
        self.conversation = {
            "id": str(uuid4()),
            "tenant_id": tenant,
            "next_turn_number": 1,
            "archived_at": None,
        }
        self.run = {
            "id": str(uuid4()),
            "tenant_id": tenant,
            "retrieval_index_version_id": str(uuid4()),
            "query_text": "Where?",
            "status": "queued",
        }
        self.turn = {
            "id": str(uuid4()),
            "tenant_id": tenant,
            "conversation_id": self.conversation["id"],
            "turn_number": 1,
            "run": self.run,
        }
        self.requests = []
        self.final_overrides = {}

    def __call__(self, request):
        self.requests.append((request.method, request.url.path))
        if request.method == "POST":
            if request.url.path == "/v1/conversations":
                return httpx.Response(201, json=self.conversation)
            return httpx.Response(
                201,
                json={
                    "idempotency_key": json.loads(request.content)["idempotency_key"],
                    **self.turn,
                },
            )
        response = _response(request)
        if request.url.path == f"/v1/query-runs/{self.run['id']}":
            return httpx.Response(
                200,
                json={
                    **response.json(),
                    **self.run,
                    "status": "completed",
                    **self.final_overrides,
                },
            )
        return response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "../../other"),
        ("tenant_id", str(uuid4())),
        ("next_turn_number", 2),
        ("next_turn_number", True),
        ("archived_at", "2026-10-11T00:00:00Z"),
    ],
)
async def test_conversation_capture_rejects_nonfresh_or_foreign_creation_before_turn(field, value):
    api = _ConversationAPI()
    api.conversation[field] = value
    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(api)
    ) as client:
        with pytest.raises(ValueError, match="Conversation capture"):
            await capture_dataset(client, _dataset(), _manifest(), conversation=True)
    assert api.requests == [("POST", "/v1/conversations")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope,field,value",
    [
        ("turn", "id", "../../other"),
        ("turn", "tenant_id", str(uuid4())),
        ("turn", "conversation_id", str(uuid4())),
        ("turn", "turn_number", 2),
        ("turn", "turn_number", True),
        ("turn", "idempotency_key", str(uuid4())),
        ("run", "id", "../../other"),
        ("run", "tenant_id", str(uuid4())),
        ("run", "retrieval_index_version_id", "bad-index"),
        ("run", "query_text", "Another question?"),
        ("run", "status", "completed"),
    ],
)
async def test_conversation_capture_rejects_mismatched_turn_before_execution(scope, field, value):
    api = _ConversationAPI()
    (api.turn if scope == "turn" else api.run)[field] = value
    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(api)
    ) as client:
        with pytest.raises(ValueError, match="Conversation capture"):
            await capture_dataset(client, _dataset(), _manifest(), conversation=True)
    assert [method for method, _path in api.requests] == ["POST", "POST"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("id", str(uuid4())),
        ("tenant_id", str(uuid4())),
        ("retrieval_index_version_id", str(uuid4())),
        ("query_text", "Another question?"),
    ],
)
async def test_conversation_capture_rejects_final_run_reference_mismatch_before_scoring(
    field, value
):
    api = _ConversationAPI()
    api.final_overrides[field] = value
    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(api)
    ) as client:
        with pytest.raises(ValueError, match="Conversation capture"):
            await capture_dataset(client, _dataset(), _manifest(), conversation=True)
    assert not any(path.endswith(("/retrieval", "/provenance")) for _, path in api.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("change_index", [False, True])
async def test_conversation_capture_creates_fresh_ordered_turns_without_client_history(
    change_index,
):
    conversation_id = str(uuid4())
    index_id = str(uuid4())
    run_ids = [str(uuid4()), str(uuid4())]
    turn_ids = [str(uuid4()), str(uuid4())]
    questions = ["Where?", "What about the prior year?"]
    submitted = []
    creations = []
    second_executed = False
    contexts = [
        {"policy_version": "fixture-memory-v1", "mode": "independent"},
        {
            "policy_version": "fixture-memory-v1",
            "mode": "resolved",
            "resolved_query": "Where in 2016?",
        },
    ]
    tenant_id = str(_manifest().tenant_id)

    def respond(request):
        nonlocal second_executed
        assert request.headers["X-Tenant-ID"] == tenant_id
        if request.method == "POST" and request.url.path == "/v1/conversations":
            creations.append(json.loads(request.content))
            return httpx.Response(
                201,
                json={
                    "id": conversation_id,
                    "tenant_id": tenant_id,
                    "next_turn_number": 1,
                    "archived_at": None,
                },
            )
        if request.method == "POST":
            assert request.url.path == f"/v1/conversations/{conversation_id}/turns"
            payload = json.loads(request.content)
            submitted.append(payload)
            number = len(submitted)
            return httpx.Response(
                201,
                json={
                    "id": turn_ids[number - 1],
                    "tenant_id": tenant_id,
                    "conversation_id": conversation_id,
                    "turn_number": number,
                    "idempotency_key": payload["idempotency_key"],
                    "run": {
                        "id": run_ids[number - 1],
                        "tenant_id": tenant_id,
                        "retrieval_index_version_id": str(uuid4())
                        if change_index and number == 2
                        else index_id,
                        "query_text": questions[number - 1],
                        "status": "queued",
                    },
                },
            )
        if request.url.path == f"/v1/query-runs/{run_ids[1]}/events/stream":
            second_executed = True
        response = _response(request)
        if request.url.path in [f"/v1/query-runs/{run_id}" for run_id in run_ids]:
            number = run_ids.index(request.url.path.rsplit("/", 1)[1])
            return httpx.Response(
                200,
                json={
                    **response.json(),
                    "id": run_ids[number],
                    "tenant_id": tenant_id,
                    "retrieval_index_version_id": index_id,
                    "query_text": questions[number],
                    "metadata": {"conversation_context": contexts[number]},
                },
            )
        return response

    dataset = _dataset().model_copy(
        update={
            "queries": [
                GoldenQuery(id="first", query=questions[0], query_type="factoid"),
                GoldenQuery(id="followup", query=questions[1], query_type="factoid"),
            ]
        }
    )
    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(respond)
    ) as client:
        if change_index:
            with pytest.raises(ValueError, match=r"Conversation capture.*index"):
                await capture_dataset(client, dataset, _manifest(), conversation=True)
            assert not second_executed
            return
        records = await capture_dataset(client, dataset, _manifest(), conversation=True)
    assert creations == [{}]
    assert [payload["query"] for payload in submitted] == questions
    assert all(set(payload) == {"query", "idempotency_key"} for payload in submitted)
    keys = [UUID(payload["idempotency_key"]) for payload in submitted]
    assert len(set(keys)) == 2
    assert [record.capture["query_run_id"] for record in records] == run_ids
    assert [record.capture["conversation_turn_id"] for record in records] == turn_ids
    assert [record.capture["conversation_turn_number"] for record in records] == [1, 2]
    assert all(record.capture["conversation_id"] == conversation_id for record in records)
    assert all(record.capture["format_version"] == 3 for record in records)
    assert all(
        record.capture["conversation_limits"]
        == {
            "max_turns": 8,
            "turn_timeout_seconds": 300.0,
            "total_timeout_seconds": 900.0,
        }
        for record in records
    )
    assert [record.capture["conversation_context"] for record in records] == contexts
    assert [record.evaluation.answer_text for record in records] == ["Berlin. [c1]", "Berlin. [c1]"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "count,query_budget", [(9, 90), (1, 301), (1, float("inf")), (1, float("nan"))]
)
async def test_conversation_capture_rejects_unbounded_configuration_before_any_http(
    count, query_budget
):
    def unexpected(request):
        raise AssertionError("Invalid conversation budgets must not create server state")

    dataset = _dataset().model_copy(
        update={
            "queries": [
                GoldenQuery(id=f"q{number}", query="Where?", query_type="factoid")
                for number in range(count)
            ]
        }
    )
    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(unexpected)
    ) as client:
        with pytest.raises(ValueError, match="Conversation capture"):
            await capture_dataset(
                client, dataset, _manifest(), conversation=True, query_timeout_seconds=query_budget
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("total_budget", [0, -1, 901, float("inf"), float("nan")])
async def test_conversation_capture_rejects_invalid_total_budget_before_http(total_budget):
    def unexpected(request):
        raise AssertionError("Invalid total budget must not create server state")

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(unexpected)
    ) as client:
        with pytest.raises(ValueError, match="Conversation capture"):
            await capture_dataset(
                client,
                _dataset(),
                _manifest(),
                conversation=True,
                conversation_timeout_seconds=total_budget,
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("http_status", [401, 403, 409])
async def test_conversation_capture_stops_on_turn_http_errors_without_retry(http_status):
    api = _ConversationAPI()

    def respond(request):
        if request.method == "POST" and request.url.path.endswith("/turns"):
            api.requests.append((request.method, request.url.path))
            return httpx.Response(http_status, json={"detail": "stop"})
        return api(request)

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(respond)
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await capture_dataset(client, _dataset(), _manifest(), conversation=True)
    assert [method for method, _ in api.requests] == ["POST", "POST"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["queued", "running", "failed", "cancelled"])
async def test_conversation_capture_stops_on_incomplete_final_turn(status):
    api = _ConversationAPI()
    api.final_overrides["status"] = status
    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(api)
    ) as client:
        with pytest.raises(ValueError, match="did not complete"):
            await capture_dataset(client, _dataset(), _manifest(), conversation=True)
    assert not any(path.endswith(("/retrieval", "/provenance")) for _, path in api.requests)


@pytest.mark.asyncio
async def test_conversation_capture_whole_deadline_includes_creation_and_turn_execution():
    api = _ConversationAPI()

    async def delayed(request):
        await asyncio.sleep(0.02)
        return api(request)

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(delayed)
    ) as client:
        with pytest.raises(TimeoutError):
            await capture_dataset(
                client,
                _dataset(),
                _manifest(),
                conversation=True,
                query_timeout_seconds=1,
                conversation_timeout_seconds=0.05,
            )
    assert len(api.requests) <= 2
    assert not any(path.endswith("/provenance") for _, path in api.requests)


@pytest.mark.asyncio
async def test_conversation_recording_retains_offline_compatibility_and_normalized_question(
    tmp_path,
):
    api = _ConversationAPI()
    dataset = _dataset().model_copy(
        update={
            "queries": [
                GoldenQuery(id="q1", query="  Where?\n", query_type="factoid"),
            ]
        }
    )
    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(api)
    ) as client:
        records = await capture_dataset(client, dataset, _manifest(), conversation=True)
    path = tmp_path / "conversation.jsonl"
    path.write_text(records[0].model_dump_json() + "\n", encoding="utf-8")
    assert records[0].capture["format_version"] == 3
    assert load_recorded_evaluations(path)["q1"] == records[0].evaluation


@pytest.mark.asyncio
async def test_conversation_capture_total_deadline_stops_even_creation_io():
    requests = []

    async def delayed(request):
        requests.append(request.url.path)
        await asyncio.sleep(0.1)
        raise AssertionError("The total deadline must stop the delayed external request")

    async with httpx.AsyncClient(
        base_url="http://test",
        transport=httpx.MockTransport(delayed),
    ) as client:
        with pytest.raises(TimeoutError):
            await capture_dataset(
                client,
                _dataset(),
                _manifest(),
                conversation=True,
                query_timeout_seconds=1,
                conversation_timeout_seconds=0.01,
            )
    assert requests == ["/v1/conversations"]


async def test_capture_records_actual_run_token_rollups_not_zero_fixture_usage():
    def respond(request):
        response = _response(request)
        if request.method == "GET" and request.url.path.endswith("/run-1"):
            body = response.json()
            body.update(provider_input_tokens=900, provider_output_tokens=120)
            return httpx.Response(200, json=body)
        return response

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(respond)
    ) as client:
        records = await capture_dataset(client, _dataset(), _manifest())
    assert records[0].evaluation.input_tokens == 900
    assert records[0].evaluation.output_tokens == 120
    assert records[0].evaluation.estimated_cost_usd is None


async def test_capture_sse_read_timeout_uses_query_budget_not_short_client_default():
    def respond(request):
        if request.url.path.endswith("/events/stream"):
            assert request.extensions["timeout"]["read"] == 90
        return _response(request)

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(respond), timeout=30
    ) as client:
        await capture_dataset(client, _dataset(), _manifest(), query_timeout_seconds=90)


def _response(request: httpx.Request, *, status: str = "completed") -> httpx.Response:
    assert request.headers["X-Tenant-ID"] == str(_manifest().tenant_id)
    path = request.url.path
    if request.method == "POST":
        assert json.loads(request.content)["query"] == "Where?"
        return httpx.Response(201, json={"id": "run-1"})
    if path.endswith("/events/stream"):
        return httpx.Response(200, text="event: query.completed\ndata: {}\n\n")
    if path.endswith("/retrieval"):
        candidate: dict[str, Any] = {
            "candidate_type": "chunk",
            "rerank_rank": 1,
            "candidate_id": "chunk-a",
            "source_ids": {"chunk_id": "chunk-a"},
            "document_id": "doc-id",
        }
        return httpx.Response(
            200,
            json={
                "candidates": [
                    candidate,
                    {**candidate, "rerank_rank": 2},
                    {**candidate, "document_id": "ignored", "rerank_rank": None},
                ],
                "linked_entity_ids": ["not-a-retrieval-hit"],
            },
        )
    if path.endswith("/provenance"):
        return httpx.Response(
            200,
            json={
                "answer_text": "Berlin. [c1]",
                "abstained": False,
                "answer_citations": [{"citation_id": "c1"}],
                "claims": [{"support_status": "supported"}, {"support_status": "partial"}],
                "citations": [
                    {
                        "citation_id": "c1",
                        "source_document_id": "doc-id",
                        "source_ids": {"chunk_id": "chunk-a"},
                        "source_active": True,
                    }
                ],
            },
        )
    return httpx.Response(
        200,
        json={
            "id": "run-1",
            "status": status,
            "retrieval_index_version_id": "index-1",
            "query_diagnostics": {"answer_provider": "deterministic"},
        },
    )


@pytest.mark.asyncio
async def test_capture_scores_actual_ranked_candidates_and_keeps_provenance() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_response), base_url="http://test"
    ) as c:
        records = await capture_dataset(c, _dataset(), _manifest(), git_sha="abc")
    record = records[0]
    assert record.evaluation.retrieved_chunk_ids == ["doc-a"]
    assert record.evaluation.retrieved_entity_ids == []
    assert record.evaluation.cited_source_ids == ["doc-a"]
    assert record.evaluation.supported_claim_count == 1
    assert record.evaluation.partial_claim_count == 1
    assert record.capture["query_run_id"] == "run-1"
    assert record.capture["git_sha"] == "abc"
    assert record.capture["retrieval_index_version_id"] == "index-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "cancelled", "running", "queued"])
async def test_capture_rejects_unsuccessful_or_incomplete_runs(status: str) -> None:
    transport = httpx.MockTransport(lambda r: _response(r, status=status))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        with pytest.raises(ValueError, match="did not complete"):
            await capture_dataset(c, _dataset(), _manifest())


@pytest.mark.asyncio
async def test_capture_rejects_unmapped_retrieval_labels() -> None:
    manifest = _manifest().model_copy(update={"document_labels": {}})
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_response), base_url="http://test"
    ) as c:
        with pytest.raises(ValueError, match="Unmapped"):
            await capture_dataset(c, _dataset(), manifest)


@pytest.mark.asyncio
async def test_capture_validates_dataset_before_creating_queries() -> None:
    def unexpected(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not create a query for a mismatched manifest")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(unexpected), base_url="http://test"
    ) as c:
        with pytest.raises(ValueError, match="dataset"):
            await capture_dataset(
                c, _dataset(), _manifest().model_copy(update={"dataset_version": 2})
            )


@pytest.mark.asyncio
async def test_capture_recording_remains_compatible_with_offline_scorer(tmp_path: Path) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_response), base_url="http://test"
    ) as client:
        records = await capture_dataset(client, _dataset(), _manifest())
    path = tmp_path / "fresh.jsonl"
    path.write_text(records[0].model_dump_json() + "\n", encoding="utf-8")
    assert load_recorded_evaluations(path)["q1"] == records[0].evaluation


@pytest.mark.asyncio
async def test_capture_reports_invalid_final_citations_without_fabricating_sources() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        response = _response(request)
        if request.url.path.endswith("/provenance"):
            body = response.json()
            body["answer_citations"] = [{"citation_id": "unknown"}]
            return httpx.Response(200, json=body)
        return response

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://test"
    ) as client:
        record = (await capture_dataset(client, _dataset(), _manifest()))[0]
    assert record.evaluation.invalid_citation_count == 1
    assert record.evaluation.cited_source_ids == []


@pytest.mark.asyncio
async def test_capture_scores_graph_candidates_not_linked_entities() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/retrieval"):
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "candidate_id": "rel",
                            "candidate_type": "relationship",
                            "rerank_rank": 1,
                            "source_ids": {"relationship_id": "r1"},
                            "subject_entity_id": "e1",
                            "object_entity_id": "e2",
                        }
                    ],
                    "linked_entity_ids": ["e3"],
                },
            )
        return _response(request)

    manifest = _manifest().model_copy(update={"entity_labels": {"e1": "Acme", "e2": "Berlin"}})
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://test"
    ) as client:
        record = (await capture_dataset(client, _dataset(), manifest))[0]
    assert record.evaluation.retrieved_entity_ids == ["Acme", "Berlin"]
    assert record.evaluation.retrieved_chunk_ids == []
