import json
from uuid import uuid4

import httpx
import pytest

from flint_graph.cli.dev import main

WORKSPACE = str(uuid4())
INDEX = str(uuid4())


def responses():
    return {
        "/health/ready": {
            "status": "ready",
            "dependencies": {
                "postgres": {"status": "ok", "required": True},
            },
        },
        "/v1/system-readiness": {
            "setup_capabilities": {"preserve_active_bootstrap": True},
            "auth": {"mode": "dev"},
            "embedding": {
                "provider": "deterministic",
                "model": "deterministic-test",
                "dimensions": 384,
            },
            "query": {
                "answer_provider": "deterministic",
                "answer_model": "deterministic",
                "support_provider": "deterministic",
                "support_model": "deterministic",
            },
            "search_readiness": {
                "ready": False,
                "active_index_version": None,
                "completed_coverage_count": 0,
                "running_coverage_count": 0,
                "failed_coverage_count": 0,
                "cancelled_coverage_count": 0,
            },
        },
        "/v1/model-readiness": [
            {"role": role, "provider": "deterministic", "model": model, "status": "offline"}
            for role, model in [
                ("embedding", "deterministic-test"),
                ("answer", "deterministic"),
                ("support", "deterministic"),
            ]
        ],
        "/v1/workspaces": [{"id": WORKSPACE, "role": "owner"}],
    }


def test_offline_profile_check_uses_public_reads_without_bootstrapping(capsys):
    data = responses()

    def serve(request):
        assert request.method == "GET"
        if request.url.path.startswith("/v1/"):
            assert request.headers["X-Tenant-ID"] == WORKSPACE
        return httpx.Response(200, json=data[request.url.path])

    assert (
        main(
            ["check", "--profile", "offline", "--workspace-id", WORKSPACE],
            transport=httpx.MockTransport(serve),
        )
        == 0
    )
    assert "offline" in capsys.readouterr().out


def test_bootstrap_preserves_existing_compatible_index_and_requires_admin(capsys):
    data = responses()
    data["/v1/system-readiness"]["search_readiness"]["active_index_version"] = {
        "id": INDEX,
        "embedding_provider": "deterministic",
        "embedding_model": "deterministic-test",
        "vector_dimension": 384,
    }

    def serve(request):
        assert request.method == "GET"
        return httpx.Response(200, json=data[request.url.path])

    assert (
        main(
            ["bootstrap", "--profile", "offline", "--workspace-id", WORKSPACE],
            transport=httpx.MockTransport(serve),
        )
        == 0
    )
    data["/v1/workspaces"][0]["role"] = "member"
    assert (
        main(
            ["bootstrap", "--profile", "offline", "--workspace-id", WORKSPACE],
            transport=httpx.MockTransport(serve),
        )
        == 1
    )
    assert "admin" in capsys.readouterr().out


def test_bootstrap_creates_only_an_absent_index_and_not_a_workspace(capsys):
    data = responses()
    writes = []

    def serve(request):
        if request.method == "POST":
            writes.append(request.url.path)
            assert request.url.path == "/v1/retrieval-index/bootstrap"
            return httpx.Response(
                200,
                json={
                    "id": INDEX,
                    "embedding_provider": "deterministic",
                    "embedding_model": "deterministic-test",
                    "vector_dimension": 384,
                },
            )
        return httpx.Response(200, json=data[request.url.path])

    assert (
        main(
            ["bootstrap", "--profile", "offline", "--workspace-id", WORKSPACE],
            transport=httpx.MockTransport(serve),
        )
        == 0
    )
    assert writes == ["/v1/retrieval-index/bootstrap"]


@pytest.mark.parametrize("broken", ["provider", "index", "model", "auth"])
def test_bootstrap_failures_never_mutate_and_redact_payloads(capsys, broken):
    data = responses()
    if broken == "provider":
        data["/v1/system-readiness"]["query"]["answer_provider"] = "ollama"
    elif broken == "index":
        data["/v1/system-readiness"]["search_readiness"]["active_index_version"] = {
            "id": INDEX,
            "embedding_provider": "ollama",
            "embedding_model": "other",
            "vector_dimension": 768,
        }
    elif broken == "model":
        data["/v1/model-readiness"][1]["status"] = "missing"

    def serve(request):
        assert request.method == "GET"
        if broken == "auth":
            return httpx.Response(403, text="private-secret")
        return httpx.Response(200, json=data[request.url.path])

    assert (
        main(
            ["bootstrap", "--profile", "offline", "--workspace-id", WORKSPACE],
            transport=httpx.MockTransport(serve),
        )
        == 1
    )
    assert "private-secret" not in capsys.readouterr().out


def local_real_responses():
    data = responses()
    data["/v1/system-readiness"]["embedding"] = {
        "provider": "ollama",
        "model": "embed:1",
        "dimensions": 768,
    }
    data["/v1/system-readiness"]["query"] = {
        "answer_provider": "ollama",
        "answer_model": "answer:1",
        "support_provider": "ollama",
        "support_model": "answer:1",
    }
    data["/v1/model-readiness"] = [
        {
            "role": role,
            "provider": "ollama",
            "model": model,
            "status": "available",
            "digest": "sha256:" + fingerprint * 64,
        }
        for role, model, fingerprint in [
            ("embedding", "embed:1", "a"),
            ("answer", "answer:1", "b"),
            ("support", "answer:1", "b"),
        ]
    ]
    return data


def test_local_real_lock_records_installed_model_digests_without_writes_to_api(tmp_path, capsys):
    output = tmp_path / "models.lock.json"
    data = local_real_responses()

    def serve(request):
        assert request.method == "GET"
        return httpx.Response(200, json=data[request.url.path])

    assert (
        main(
            [
                "lock",
                "--profile",
                "local-real",
                "--workspace-id",
                WORKSPACE,
                "--output",
                str(output),
            ],
            transport=httpx.MockTransport(serve),
        )
        == 0
    )
    lock = json.loads(output.read_text())
    assert lock["embedding"]["dimensions"] == 768
    assert lock["models"][0]["digest"] == "sha256:" + "a" * 64
    assert "status" not in lock["models"][0]
    assert (
        main(
            [
                "check",
                "--profile",
                "local-real",
                "--workspace-id",
                WORKSPACE,
                "--model-lock",
                str(output),
            ],
            transport=httpx.MockTransport(serve),
        )
        == 0
    )


@pytest.mark.parametrize("changed", ["digest", "dimensions", "missing", "unversioned"])
def test_local_real_refuses_missing_or_changed_models_before_bootstrap(tmp_path, capsys, changed):
    output = tmp_path / "models.lock.json"
    data = local_real_responses()

    def serve(request):
        assert request.method == "GET"
        return httpx.Response(200, json=data[request.url.path])

    assert (
        main(
            [
                "lock",
                "--profile",
                "local-real",
                "--workspace-id",
                WORKSPACE,
                "--output",
                str(output),
            ],
            transport=httpx.MockTransport(serve),
        )
        == 0
    )
    if changed == "digest":
        data["/v1/model-readiness"][0]["digest"] = "sha256:" + "c" * 64
    elif changed == "dimensions":
        data["/v1/system-readiness"]["embedding"]["dimensions"] = 384
    elif changed == "missing":
        data["/v1/model-readiness"][1]["status"] = "missing"
    else:
        data["/v1/system-readiness"]["query"]["answer_model"] = "answer"
        data["/v1/model-readiness"][1]["model"] = "answer"
    assert (
        main(
            [
                "bootstrap",
                "--profile",
                "local-real",
                "--workspace-id",
                WORKSPACE,
                "--model-lock",
                str(output),
            ],
            transport=httpx.MockTransport(serve),
        )
        == 1
    )


def test_local_real_requires_a_lock_and_never_overwrites_one(tmp_path, capsys):
    data = local_real_responses()

    def serve(request):
        assert request.method == "GET"
        return httpx.Response(200, json=data[request.url.path])

    assert (
        main(
            ["bootstrap", "--profile", "local-real", "--workspace-id", WORKSPACE],
            transport=httpx.MockTransport(serve),
        )
        == 1
    )
    output = tmp_path / "models.lock.json"
    output.write_text("keep-me")
    assert (
        main(
            [
                "lock",
                "--profile",
                "local-real",
                "--workspace-id",
                WORKSPACE,
                "--output",
                str(output),
            ],
            transport=httpx.MockTransport(serve),
        )
        == 1
    )
    assert output.read_text() == "keep-me"


def test_opt_in_smoke_corpus_reuses_prepare_and_existing_workspace(tmp_path, capsys):
    dataset = tmp_path / "dataset"
    (dataset / "corpus").mkdir(parents=True)
    (dataset / "dataset.yaml").write_text("name: mini\nversion: 1\ntenant: eval\n")
    (dataset / "queries.jsonl").write_text(
        '{"id":"q1","query":"Where is Acme?","query_type":"factoid"}\n'
    )
    (dataset / "corpus" / "acme.md").write_text("# Acme\n\nAcme is in Berlin.\n")
    data = responses()
    data["/v1/system-readiness"]["search_readiness"]["active_index_version"] = {
        "id": INDEX,
        "embedding_provider": "deterministic",
        "embedding_model": "deterministic-test",
        "vector_dimension": 384,
    }
    document, version, job = (str(uuid4()) for _ in range(3))
    keys = []

    def serve(request):
        path = request.url.path
        assert request.method != "DELETE"
        if path.endswith("/uploads"):
            keys.append(request.headers["Idempotency-Key"])
            return httpx.Response(
                201,
                json={
                    "document_id": document,
                    "document_version_id": version,
                    "ingestion_job_id": job,
                },
            )
        if "/ingestion-jobs/" in path:
            return httpx.Response(200, json={"status": "completed"})
        if path.endswith("/index-coverage"):
            return httpx.Response(
                200,
                json=[
                    {
                        "document_version_id": version,
                        "retrieval_index_version_id": INDEX,
                        "status": "completed",
                        "chunk_count": 1,
                    }
                ],
            )
        if "/search/" in path:
            return httpx.Response(200, json={"results": [{"document_version_id": version}]})
        if path.endswith("/entities"):
            return httpx.Response(200, json=[])
        assert request.method == "GET"
        return httpx.Response(200, json=data[path])

    manifests = []
    for number in range(2):
        output = tmp_path / f"manifest-{number}.json"
        assert (
            main(
                [
                    "bootstrap",
                    "--profile",
                    "offline",
                    "--workspace-id",
                    WORKSPACE,
                    "--smoke-corpus",
                    "--dataset",
                    str(dataset),
                    "--output",
                    str(output),
                ],
                transport=httpx.MockTransport(serve),
            )
            == 0
        )
        manifests.append(json.loads(output.read_text()))
    assert keys[0] == keys[1]
    assert manifests[0]["document_labels"] == manifests[1]["document_labels"] == {document: "acme"}
    assert manifests[0]["preparation"]["developer_profile"] == "offline"


def test_old_api_without_guard_capability_cannot_create_an_index(capsys):
    data = responses()
    data["/v1/system-readiness"].pop("setup_capabilities")

    def serve(request):
        assert request.method == "GET"
        return httpx.Response(200, json=data[request.url.path])

    assert (
        main(
            ["bootstrap", "--profile", "offline", "--workspace-id", WORKSPACE],
            transport=httpx.MockTransport(serve),
        )
        == 1
    )
    assert "upgrade" in capsys.readouterr().out.lower()


def test_null_capabilities_fail_safely_without_bootstrap(capsys):
    data = responses()
    data["/v1/system-readiness"]["setup_capabilities"] = None

    def serve(request):
        assert request.method == "GET"
        return httpx.Response(200, json=data[request.url.path])

    assert (
        main(
            ["bootstrap", "--profile", "offline", "--workspace-id", WORKSPACE],
            transport=httpx.MockTransport(serve),
        )
        == 1
    )
