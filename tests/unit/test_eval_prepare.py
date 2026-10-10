from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from flint_graph.evaluation.datasets import load_dataset
from flint_graph.evaluation.prepare import load_corpus, prepare_corpus


def _corpus(tmp_path: Path) -> Path:
    (tmp_path / "dataset.yaml").write_text(
        "name: mini\nversion: 1\ntenant: eval\n", encoding="utf-8"
    )
    (tmp_path / "queries.jsonl").write_text(
        json.dumps(
            {
                "id": "q1",
                "query": "Where is Acme?",
                "query_type": "factoid",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "corpus").mkdir()
    (tmp_path / "corpus" / "acme.md").write_text("# Acme\n\nAcme is in Berlin.\n", encoding="utf-8")
    return tmp_path


def test_corpus_preflight_rejects_traversal(tmp_path: Path) -> None:
    directory = _corpus(tmp_path)
    dataset = load_dataset(directory)
    dataset = dataset.model_copy(
        update={
            "metadata": dataset.metadata.model_copy(update={"corpus_dir": "../"}),
        }
    )
    with pytest.raises(ValueError, match="within"):
        load_corpus(directory, dataset)


def test_corpus_preflight_rejects_duplicate_labels_and_unsupported_files(tmp_path: Path) -> None:
    directory = _corpus(tmp_path)
    (directory / "corpus" / "acme.txt").write_text("duplicate", encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        load_corpus(directory, load_dataset(directory))
    (directory / "corpus" / "acme.txt").unlink()
    (directory / "corpus" / "blob.bin").write_bytes(b"\x00")
    with pytest.raises(ValueError, match="Unsupported"):
        load_corpus(directory, load_dataset(directory))


@pytest.mark.asyncio
async def test_prepare_waits_for_real_projection_visibility_and_returns_manifest(
    tmp_path: Path,
) -> None:
    directory = _corpus(tmp_path)
    dataset = load_dataset(directory)
    workspace_id, index_id, document_id, version_id, entity_id = (uuid4() for _ in range(5))
    job_id = uuid4()
    probes: list[str] = []
    created_workspaces: list[object] = []

    def respond(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/workspaces":
            return httpx.Response(201, json={"id": str(workspace_id), "name": "eval"})
        assert request.headers["X-Tenant-ID"] == str(workspace_id)
        if path.endswith("/bootstrap"):
            return httpx.Response(200, json={"id": str(index_id), "status": "active"})
        if path.endswith("/uploads"):
            assert request.headers["Idempotency-Key"]
            assert b"Acme is in Berlin" in request.content
            assert b"text/markdown" in request.content
            return httpx.Response(
                201,
                json={
                    "document_id": str(document_id),
                    "document_version_id": str(version_id),
                    "ingestion_job_id": str(job_id),
                },
            )
        if "/ingestion-jobs/" in path:
            return httpx.Response(200, json={"status": "completed"})
        if path.endswith("/index-coverage"):
            return httpx.Response(
                200,
                json=[
                    {
                        "document_version_id": str(version_id),
                        "retrieval_index_version_id": str(index_id),
                        "status": "completed",
                        "chunk_count": 1,
                    }
                ],
            )
        if "/search/" in path:
            assert json.loads(request.content)["filters"]["document_version_id"] == str(version_id)
            probes.append(path)
            # A completed Postgres coverage row must not short-circuit projection polling.
            results = [] if len(probes) <= 2 else [{"document_version_id": str(version_id)}]
            return httpx.Response(200, json={"results": results})
        if path.endswith("/entities"):
            return httpx.Response(200, json=[{"id": str(entity_id), "canonical_name": "Acme"}])
        if path.endswith("/system-readiness"):
            return httpx.Response(200, json={"embedding": {"provider": "deterministic"}})
        raise AssertionError(path)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://test"
    ) as c:
        manifest = await prepare_corpus(
            c,
            dataset,
            load_corpus(directory, dataset),
            poll_interval_seconds=0,
            on_workspace_created=created_workspaces.append,
        )
    assert created_workspaces == [workspace_id]
    assert manifest.tenant_id == workspace_id
    assert manifest.document_labels == {str(document_id): "acme"}
    assert manifest.entity_labels == {str(entity_id): "Acme"}
    assert len(probes) == 4
    assert manifest.preparation["retrieval_index_version_id"] == str(index_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_status", ["failed", "cancelled"])
async def test_prepare_rejects_failed_ingestion_without_deleting_workspace(
    tmp_path: Path,
    terminal_status: str,
) -> None:
    directory = _corpus(tmp_path)
    dataset = load_dataset(directory)
    workspace_id = uuid4()

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method != "DELETE"
        if request.url.path == "/v1/workspaces":
            return httpx.Response(201, json={"id": str(workspace_id)})
        if request.url.path.endswith("/bootstrap"):
            return httpx.Response(200, json={"id": str(uuid4()), "status": "active"})
        if request.url.path.endswith("/uploads"):
            return httpx.Response(
                201,
                json={
                    "document_id": str(uuid4()),
                    "document_version_id": str(uuid4()),
                    "ingestion_job_id": str(uuid4()),
                },
            )
        return httpx.Response(200, json={"status": terminal_status})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://test"
    ) as c:
        with pytest.raises(ValueError, match=terminal_status):
            await prepare_corpus(
                c, dataset, load_corpus(directory, dataset), poll_interval_seconds=0
            )


@pytest.mark.asyncio
async def test_prepare_times_out_with_inspectable_workspace_not_a_false_success(
    tmp_path: Path,
) -> None:
    directory = _corpus(tmp_path)
    dataset = load_dataset(directory)
    workspace_id = uuid4()

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/workspaces":
            return httpx.Response(201, json={"id": str(workspace_id)})
        if request.url.path.endswith("/bootstrap"):
            return httpx.Response(200, json={"id": str(uuid4())})
        if request.url.path.endswith("/uploads"):
            return httpx.Response(
                201,
                json={
                    "document_id": str(uuid4()),
                    "document_version_id": str(uuid4()),
                    "ingestion_job_id": str(uuid4()),
                },
            )
        if request.url.path.endswith("/index-coverage"):
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"status": "queued"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://test"
    ) as c:
        with pytest.raises(ValueError, match=str(workspace_id)):
            await prepare_corpus(
                c,
                dataset,
                load_corpus(directory, dataset),
                timeout_seconds=0.05,
                poll_interval_seconds=0.01,
            )
