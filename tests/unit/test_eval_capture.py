from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

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
