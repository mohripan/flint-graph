from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from flint_graph.evaluation.datasets import load_dataset
from flint_graph.evaluation.prepare import load_corpus, prepare_corpus, verify_prepared_corpus


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


@pytest.mark.parametrize("failure", [None, "index", "document", "projection"])
async def test_verify_existing_corpus_never_uploads_or_bootstraps_and_requires_both_projections(
    tmp_path,
    failure,
):
    directory = _corpus(tmp_path)
    dataset = load_dataset(directory)
    workspace_id, index_id, document_id, version_id = (uuid4() for _ in range(4))
    probes = []

    def respond(request):
        assert request.headers["X-Tenant-ID"] == str(workspace_id)
        if request.url.path == "/v1/system-readiness":
            return httpx.Response(
                200,
                json={
                    "search_readiness": {
                        "active_index_version": {
                            "id": str(uuid4() if failure == "index" else index_id)
                        },
                    }
                },
            )
        if request.url.path == "/v1/documents":
            return httpx.Response(
                200,
                json=[]
                if failure == "document"
                else [
                    {
                        "id": str(document_id),
                        "title": "acme",
                        "latest_version_id": str(version_id),
                        "latest_version_status": "active",
                    }
                ],
            )
        if request.url.path == "/v1/index-coverage":
            assert request.url.params["document_version_id"] == str(version_id)
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
        if request.url.path.startswith("/v1/search/"):
            probes.append(request.url.path)
            body = json.loads(request.content)
            assert body["filters"]["document_version_id"] == str(version_id)
            return httpx.Response(
                200,
                json={
                    "results": []
                    if failure == "projection"
                    else [
                        {
                            "document_version_id": str(version_id),
                        }
                    ]
                },
            )
        if request.url.path == "/v1/entities":
            return httpx.Response(200, json=[])
        pytest.fail(f"Unexpected mutation/read: {request.url.path}")

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(respond)
    ) as client:
        if failure:
            with pytest.raises(ValueError):
                await verify_prepared_corpus(
                    client,
                    dataset,
                    load_corpus(directory, dataset),
                    workspace_id=workspace_id,
                    index_version_id=index_id,
                    timeout_seconds=1,
                )
        else:
            manifest = await verify_prepared_corpus(
                client,
                dataset,
                load_corpus(directory, dataset),
                workspace_id=workspace_id,
                index_version_id=index_id,
            )
            assert manifest.document_labels == {str(document_id): "acme"}
            assert manifest.preparation["projection_visibility_probed"] is True
            assert probes == ["/v1/search/lexical", "/v1/search/vector"]


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


async def test_prepare_can_resume_an_existing_workspace_without_switching_its_index(tmp_path):
    directory = _corpus(tmp_path)
    dataset = load_dataset(directory)
    workspace_id, index_id, document_id, version_id, job_id = (uuid4() for _ in range(5))
    keys = []
    external_ids = []

    def respond(request):
        assert request.method != "DELETE"
        assert request.headers["X-Tenant-ID"] == str(workspace_id)
        path = request.url.path
        if path.endswith("/system-readiness"):
            return httpx.Response(
                200,
                json={
                    "search_readiness": {
                        "active_index_version": {"id": str(index_id)},
                    }
                },
            )
        if path.endswith("/uploads"):
            keys.append(request.headers["Idempotency-Key"])
            external_ids.append(
                request.content.split(b'name="external_id"')[1]
                .split(b"\r\n\r\n")[1]
                .split(b"\r\n")[0]
            )
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
            return httpx.Response(200, json={"results": [{"document_version_id": str(version_id)}]})
        if path.endswith("/entities"):
            return httpx.Response(200, json=[])
        pytest.fail(f"Unexpected mutation or request: {request.method} {path}")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://test"
    ) as c:
        first = await prepare_corpus(
            c,
            dataset,
            load_corpus(directory, dataset),
            workspace_id=workspace_id,
            index_version_id=index_id,
        )
        second = await prepare_corpus(
            c,
            dataset,
            load_corpus(directory, dataset),
            workspace_id=workspace_id,
            index_version_id=index_id,
        )
        (directory / "corpus" / "acme.md").write_text("# Acme\n\nAcme is now in Paris.\n")
        await prepare_corpus(
            c,
            dataset,
            load_corpus(directory, dataset),
            workspace_id=workspace_id,
            index_version_id=index_id,
        )
    assert first.tenant_id == second.tenant_id == workspace_id
    assert first.document_labels == second.document_labels == {str(document_id): "acme"}
    assert keys[0] == keys[1]
    assert keys[2] != keys[1]
    assert external_ids[0] == external_ids[1] == external_ids[2]
