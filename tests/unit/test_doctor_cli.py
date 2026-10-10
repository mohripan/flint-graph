import json
from uuid import uuid4

import httpx
import pytest

from flint_graph.cli.doctor import main

WORKSPACE = str(uuid4())
INDEX = str(uuid4())


def payloads():
    return {
        "/health/live": {"status": "ok"},
        "/health/ready": {
            "status": "ready",
            "dependencies": {
                "postgres": {"status": "ok", "required": True, "detail": "private-secret"},
            },
        },
        "/v1/system-readiness": {
            "auth": {"mode": "dev", "oidc_issuer": "private-secret"},
            "embedding": {
                "provider": "deterministic",
                "model": "deterministic-test",
                "dimensions": 384,
            },
            "query": {
                "answer_provider": "ollama",
                "answer_model": "local:latest",
                "support_provider": "ollama",
                "support_model": "local:latest",
            },
            "search_readiness": {
                "ready": True,
                "reason": "ready",
                "active_index_version": {
                    "id": INDEX,
                    "embedding_provider": "deterministic",
                    "embedding_model": "deterministic-test",
                    "vector_dimension": 384,
                },
                "completed_coverage_count": 7,
                "running_coverage_count": 0,
                "failed_coverage_count": 0,
                "cancelled_coverage_count": 0,
                "documents": [{"title": "private-secret", "error_message": "private-secret"}],
            },
        },
        "/v1/model-readiness": [
            {
                "role": "embedding",
                "provider": "deterministic",
                "model": "deterministic-test",
                "status": "offline",
            },
            {
                "role": "answer",
                "provider": "ollama",
                "model": "local:latest",
                "status": "available",
            },
            {
                "role": "support",
                "provider": "ollama",
                "model": "local:latest",
                "status": "available",
            },
        ],
    }


def run_doctor(capsys, monkeypatch, responses, *, failure_path=None, response=None):
    requests = []
    monkeypatch.setenv("DOCTOR_TEST_TOKEN", "private-secret")

    def serve(request):
        requests.append(request)
        assert request.method == "GET"
        if request.url.path.startswith("/v1/"):
            assert request.headers["X-Tenant-ID"] == WORKSPACE
            assert request.headers["Authorization"] == "Bearer private-secret"
        else:
            assert "Authorization" not in request.headers
        if request.url.path == failure_path:
            return response
        return httpx.Response(200, json=responses[request.url.path])

    result = main(
        ["--workspace-id", WORKSPACE, "--token-env", "DOCTOR_TEST_TOKEN", "--json"],
        transport=httpx.MockTransport(serve),
    )
    output = capsys.readouterr().out
    assert "private-secret" not in output
    return result, json.loads(output), requests


def test_live_report_is_read_only_tenant_scoped_and_redacted(capsys, monkeypatch):
    result, report, requests = run_doctor(capsys, monkeypatch, payloads())
    assert result == 0
    assert len(requests) == 4
    assert report["scope"] == "live"
    assert report["configuration"]["embedding"]["dimensions"] == 384
    assert report["recent_coverage"]["completed"] == 7
    assert report["active_index"]["id"] == INDEX
    assert all(check["status"] != "fail" for check in report["checks"])


def test_offline_mode_makes_no_network_calls_or_settings_validation(capsys, monkeypatch):
    monkeypatch.delenv("FLINT_GRAPH_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("FLINT_GRAPH_ENV", "production")

    def reject(request):
        pytest.fail("offline mode made a network request")

    assert main(["--offline", "--json"], transport=httpx.MockTransport(reject)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["scope"] == "offline"
    assert report["configuration"] is None
    assert "not checked" in str(report).lower()


@pytest.mark.parametrize("status", ["missing", "unavailable", "unknown"])
def test_model_checks_have_meaningful_exit_codes(capsys, monkeypatch, status):
    responses = payloads()
    responses["/v1/model-readiness"][1]["status"] = status
    result, report, _ = run_doctor(capsys, monkeypatch, responses)
    assert result == (3 if status == "unknown" else 1)
    check = next(item for item in report["checks"] if item["name"] == "model.answer")
    assert check["next_step"]


@pytest.mark.parametrize("code", [401, 403, 404, 500, 302])
def test_http_failures_are_actionable_and_never_echo_bodies(capsys, monkeypatch, code):
    result, report, requests = run_doctor(
        capsys,
        monkeypatch,
        payloads(),
        failure_path="/v1/system-readiness",
        response=httpx.Response(
            code, text="private-secret", headers={"Location": "https://private-secret.invalid"}
        ),
    )
    assert result == 1
    assert all(request.url.host == "localhost" for request in requests)
    assert any(item["status"] == "fail" and item["next_step"] for item in report["checks"])


@pytest.mark.parametrize("broken", ["no_index", "no_coverage", "dimensions", "model"])
def test_search_readiness_and_embedding_compatibility_block(capsys, monkeypatch, broken):
    responses = payloads()
    search = responses["/v1/system-readiness"]["search_readiness"]
    if broken == "no_index":
        search["active_index_version"] = None
        search["ready"] = False
    elif broken == "no_coverage":
        search["ready"] = False
        search["completed_coverage_count"] = 0
    elif broken == "dimensions":
        search["active_index_version"]["vector_dimension"] = 768
    else:
        search["active_index_version"]["embedding_model"] = "different"
    result, report, _ = run_doctor(capsys, monkeypatch, responses)
    assert result == 1
    assert any("Setup" in str(check["next_step"]) for check in report["checks"])


@pytest.mark.parametrize("invalid", [None, [], {"status": "private-secret"}, {"status": "ready"}])
def test_malformed_service_reports_are_not_treated_as_healthy(capsys, monkeypatch, invalid):
    result, _, _ = run_doctor(
        capsys,
        monkeypatch,
        payloads(),
        failure_path="/health/ready",
        response=httpx.Response(200, json=invalid),
    )
    assert result == 1


def test_503_readiness_still_reports_individual_services(capsys, monkeypatch):
    response = httpx.Response(
        503,
        json={
            "status": "unavailable",
            "detail": "private-secret",
            "dependencies": {"postgres": {"status": "unavailable", "required": True}},
        },
    )
    result, report, _ = run_doctor(
        capsys,
        monkeypatch,
        payloads(),
        failure_path="/health/ready",
        response=response,
    )
    assert result == 1
    assert any(check["name"] == "service.postgres" for check in report["checks"])


def test_transport_errors_are_safe_and_do_not_abort_remaining_checks(capsys):
    def fail(request):
        raise httpx.ConnectError("private-secret", request=request)

    assert main(["--workspace-id", WORKSPACE, "--json"], transport=httpx.MockTransport(fail)) == 1
    output = capsys.readouterr().out
    assert "private-secret" not in output
    assert len([item for item in json.loads(output)["checks"] if item["status"] == "fail"]) == 4


@pytest.mark.parametrize(
    "url",
    [
        "http://remote.invalid",
        "https://user:secret@host.invalid",
        "https://host.invalid?token=secret",
        "ftp://host.invalid",
    ],
)
def test_unsafe_endpoints_are_rejected_without_echoing_credentials(capsys, url):
    assert main(["--workspace-id", WORKSPACE, "--base-url", url]) == 2
    assert "secret" not in capsys.readouterr().out


def test_missing_workspace_is_usage_error(capsys):
    assert main([]) == 2
    assert "workspace" in capsys.readouterr().out.lower()


def test_unprobed_services_are_explicit_not_implied_healthy(capsys, monkeypatch):
    _, report, _ = run_doctor(capsys, monkeypatch, payloads())
    assert any(
        check["name"] == "service.temporal" and "not checked" in check["message"]
        for check in report["checks"]
    )


@pytest.mark.parametrize("broken", ["missing_role", "duplicate_role", "configuration"])
def test_incomplete_or_inconsistent_model_reports_fail(capsys, monkeypatch, broken):
    responses = payloads()
    models = responses["/v1/model-readiness"]
    if broken == "missing_role":
        models.pop()
    elif broken == "duplicate_role":
        models[2]["role"] = "answer"
    else:
        models[1]["model"] = "not-the-configured-model"
    result, _, _ = run_doctor(capsys, monkeypatch, responses)
    assert result == 1


def test_oversized_api_reports_fail_safely(capsys, monkeypatch):
    result, _, _ = run_doctor(
        capsys,
        monkeypatch,
        payloads(),
        failure_path="/health/ready",
        response=httpx.Response(200, text="private-secret" * 200000),
    )
    assert result == 1
