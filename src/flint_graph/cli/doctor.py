"""Read-only setup diagnostics using public APIs, never model inference."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import shutil
from collections.abc import Sequence
from typing import Annotated, Any, Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, Field, ValidationError

Name = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[\w./:@+\-]+$")]
Count = Annotated[int, Field(strict=True, ge=0)]
Provider = Literal["deterministic", "ollama", "anthropic", "openai_compatible"]


class EmbeddingConfig(BaseModel):
    provider: Provider
    model: Name
    dimensions: Annotated[int, Field(strict=True, gt=0)]


class QueryConfig(BaseModel):
    answer_provider: Provider
    answer_model: Name
    support_provider: Provider
    support_model: Name


class AuthConfig(BaseModel):
    mode: Literal["dev", "oidc"]


class ActiveIndex(BaseModel):
    id: UUID
    embedding_provider: Provider
    embedding_model: Name
    vector_dimension: Annotated[int, Field(strict=True, gt=0)]


class SearchReport(BaseModel):
    ready: Annotated[bool, Field(strict=True)]
    active_index_version: ActiveIndex | None
    completed_coverage_count: Count
    running_coverage_count: Count
    failed_coverage_count: Count
    cancelled_coverage_count: Count


class SystemReport(BaseModel):
    auth: AuthConfig
    embedding: EmbeddingConfig
    query: QueryConfig
    search_readiness: SearchReport


class DependencyReport(BaseModel):
    status: Literal["ok", "unavailable", "timeout", "unknown"]
    required: Annotated[bool, Field(strict=True)]


class HealthReport(BaseModel):
    status: Literal["ready", "degraded", "unavailable"]
    dependencies: dict[str, DependencyReport] = Field(min_length=1)


class LiveReport(BaseModel):
    status: Literal["ok"]


class ModelReport(BaseModel):
    role: Literal["embedding", "answer", "support"]
    provider: Provider
    model: Name
    status: Literal["available", "missing", "unavailable", "unknown", "offline"]


SERVICE_NAMES = frozenset(
    {
        "postgres",
        "object_store",
        "temporal",
        "neo4j",
        "opensearch",
        "embedding_provider",
        "answer_provider",
    }
)


def _check(
    report: dict[str, Any], name: str, status: str, message: str, next_step: str = ""
) -> None:
    report["checks"].append(
        {
            "name": name,
            "status": status,
            "message": message,
            "next_step": next_step,
        }
    )


def _get(
    client: httpx.Client,
    report: dict[str, Any],
    path: str,
    headers: dict[str, str],
    *,
    accept_unavailable: bool = False,
) -> Any:
    try:
        # Bound diagnostic responses, and never follow a redirect with credentials.
        with client.stream("GET", path, headers=headers) as response:
            if response.status_code != 200 and not (
                accept_unavailable and response.status_code == 503
            ):
                step = "Check the API URL and service logs."
                if response.status_code in (401, 403):
                    step = "Set a valid token via --token-env and verify workspace membership."
                elif response.status_code == 404:
                    step = "Verify workspace and API version; upgrade if this endpoint is absent."
                _check(report, path, "fail", f"HTTP {response.status_code}", step)
                return None
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > 2 * 1024 * 1024:
                    raise ValueError("oversized report")
            payload = json.loads(body)
            if payload is None:
                raise ValueError("empty report")
            return payload
    except (httpx.HTTPError, ValueError):
        _check(
            report,
            path,
            "fail",
            "API unavailable or invalid diagnostic response.",
            "Check the API URL, TLS, service logs and --timeout.",
        )
        return None


def _validate(report: dict[str, Any], path: str, model: type[BaseModel], payload: Any) -> Any:
    if payload is None:
        return None
    try:
        return model.model_validate(payload)
    except ValidationError:
        _check(
            report,
            path,
            "fail",
            "Malformed diagnostic response.",
            "Check that the API and doctor versions are compatible.",
        )
        return None


def _live_checks(client: httpx.Client, report: dict[str, Any], headers: dict[str, str]) -> None:
    live = _validate(report, "/health/live", LiveReport, _get(client, report, "health/live", {}))
    if live is not None:
        _check(report, "api.live", "pass", "API process is responding.")
    health = _validate(
        report,
        "/health/ready",
        HealthReport,
        _get(client, report, "health/ready", {}, accept_unavailable=True),
    )
    if health is not None:
        if not SERVICE_NAMES.intersection(health.dependencies):
            _check(
                report,
                "api.dependencies",
                "fail",
                "No recognized service checks.",
                "Check that the API and doctor versions are compatible.",
            )
        for name, dependency in health.dependencies.items():
            if name not in SERVICE_NAMES:
                continue
            status = {"ok": "pass", "unavailable": "fail", "timeout": "fail", "unknown": "unknown"}[
                dependency.status
            ]
            _check(
                report,
                f"service.{name}",
                status,
                dependency.status,
                "Inspect this service's configuration and logs." if status != "pass" else "",
            )
        for name in sorted(SERVICE_NAMES.difference(health.dependencies)):
            _check(
                report,
                f"service.{name}",
                "warn",
                "Service not checked by API readiness.",
                "Configure API readiness dependencies to probe this service if needed.",
            )
        if health.status != "ready":
            _check(
                report,
                "api.ready",
                "fail",
                health.status,
                "Resolve failed dependencies; readiness is not an inference test.",
            )

    system = _validate(
        report,
        "/v1/system-readiness",
        SystemReport,
        _get(client, report, "v1/system-readiness", headers),
    )
    if system is not None:
        report["configuration"] = system.model_dump(mode="json", exclude={"search_readiness"})
        search = system.search_readiness
        report["recent_coverage"] = {
            "completed": search.completed_coverage_count,
            "running": search.running_coverage_count,
            "failed": search.failed_coverage_count,
            "cancelled": search.cancelled_coverage_count,
        }
        index = search.active_index_version
        report["active_index"] = index.model_dump(mode="json") if index else None
        _check(
            report,
            "search.coverage",
            "pass" if search.ready else "fail",
            "Recent document coverage is searchable."
            if search.ready
            else "No searchable recent document coverage.",
            "Use Setup to inspect the active index, ingestion and backfill."
            if not search.ready
            else "",
        )
        if index is not None:
            compatible = (
                index.embedding_provider == system.embedding.provider
                and index.embedding_model == system.embedding.model
                and index.vector_dimension == system.embedding.dimensions
            )
            _check(
                report,
                "search.embedding_compatibility",
                "pass" if compatible else "fail",
                "Active index matches configured embeddings."
                if compatible
                else "Active index differs from configured embeddings.",
                "Use Setup to select a compatible index and backfill; do not reset data."
                if not compatible
                else "",
            )
        if search.failed_coverage_count:
            _check(
                report,
                "search.failed_coverage",
                "warn",
                "Recent indexing failures exist.",
                "Inspect failed coverage in Setup before retrying.",
            )
        if system.auth.mode == "dev":
            _check(
                report,
                "auth.mode",
                "warn",
                "Development auth is not production auth.",
                "Use OIDC and workspace membership for shared deployments.",
            )

    payload = _get(client, report, "v1/model-readiness", headers)
    if payload is not None:
        try:
            if not isinstance(payload, list):
                raise ValueError("expected models")
            models = [ModelReport.model_validate(item) for item in payload]
            if sorted(item.role for item in models) != ["answer", "embedding", "support"]:
                raise ValueError("missing or duplicate roles")
            if system is not None:
                expected = {
                    "embedding": (system.embedding.provider, system.embedding.model),
                    "answer": (system.query.answer_provider, system.query.answer_model),
                    "support": (system.query.support_provider, system.query.support_model),
                }
                if any((item.provider, item.model) != expected[item.role] for item in models):
                    raise ValueError("configuration changed between requests")
        except (ValidationError, ValueError):
            _check(
                report,
                "models",
                "fail",
                "Malformed model readiness response.",
                "Check that the API and doctor versions are compatible.",
            )
        else:
            report["models"] = [item.model_dump() for item in models]
            for item in models:
                status = {
                    "available": "pass",
                    "offline": "warn",
                    "unknown": "unknown",
                    "missing": "fail",
                    "unavailable": "fail",
                }[item.status]
                steps = {
                    "available": "",
                    "offline": "Deterministic fixtures do not establish real-model answer quality.",
                    "unknown": "Unverified model; run an explicitly approved live eval.",
                    "missing": "Select an installed model or provision it; no automatic downloads.",
                    "unavailable": "Check the provider endpoint and service logs.",
                }
                _check(report, f"model.{item.role}", status, item.status, steps[item.status])


def main(argv: Sequence[str] | None = None, *, transport: httpx.BaseTransport | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline", action="store_true", help="Only inspect local tooling; no network."
    )
    parser.add_argument(
        "--base-url", default="http://localhost:8000", help="API URL, not a provider URL."
    )
    parser.add_argument("--workspace-id", help="Existing workspace UUID; required for live checks.")
    parser.add_argument(
        "--token-env", default="FLINT_GRAPH_API_TOKEN", help="Bearer-token environment variable."
    )
    parser.add_argument(
        "--timeout", type=float, default=20.0, help="Per-request timeout in seconds (max 120)."
    )
    parser.add_argument("--json", action="store_true", help="Print a structured, redacted report.")
    args = parser.parse_args(argv)
    report: dict[str, Any] = {
        "scope": "offline" if args.offline else "live",
        "checks": [],
        "configuration": None,
        "active_index": None,
        "recent_coverage": None,
        "models": None,
        "runtime": {"python": platform.python_version()},
    }
    for tool in ("uv", "docker", "node"):
        found = shutil.which(tool) is not None
        _check(
            report,
            f"tool.{tool}",
            "pass" if found else "warn",
            "Executable found on PATH (not a version or daemon check)."
            if found
            else "Executable not found on PATH.",
            "Install only if required for your development workflow." if not found else "",
        )
    if args.offline:
        _check(
            report,
            "offline.scope",
            "warn",
            "Services, models and workspace coverage not checked.",
            "Run without --offline and specify --workspace-id to check a running API.",
        )
        exit_code = 0
    else:
        try:
            url = httpx.URL(args.base_url)
            if (
                url.scheme not in ("http", "https")
                or not url.host
                or url.username
                or url.password
                or url.query
                or url.fragment
                or (url.scheme == "http" and url.host not in ("localhost", "127.0.0.1", "::1"))
            ):
                raise ValueError("unsafe URL")
            workspace = str(UUID(args.workspace_id or ""))
            if not math.isfinite(args.timeout) or not 0 < args.timeout <= 120:
                raise ValueError("invalid timeout")
            token = os.environ.get(args.token_env, "")
            if len(token) > 8192 or any(ord(char) < 33 or ord(char) > 126 for char in token):
                raise ValueError("invalid token")
        except (ValueError, httpx.InvalidURL):
            _check(
                report,
                "arguments",
                "fail",
                "Specify workspace UUID, HTTPS (or loopback HTTP), and timeout >0 and <=120.",
                "No URL credentials, query or fragment; tokens belong in --token-env.",
            )
            exit_code = 2
        else:
            headers = {"X-Tenant-ID": workspace}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            with httpx.Client(
                base_url=str(url).rstrip("/") + "/",
                timeout=args.timeout,
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            ) as client:
                _live_checks(client, report, headers)
            statuses = {check["status"] for check in report["checks"]}
            exit_code = 1 if "fail" in statuses else 3 if "unknown" in statuses else 0
    report["exit_code"] = exit_code
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        print(f"FlintGraph doctor ({report['scope']}; exit {exit_code})")
        if report["configuration"] is not None:
            print("Configuration: " + json.dumps(report["configuration"]))
            print("Active index: " + json.dumps(report["active_index"]))
            print("Recent coverage (not corpus totals): " + json.dumps(report["recent_coverage"]))
            print("Models: " + json.dumps(report["models"]))
        for check in report["checks"]:
            print(f"[{check['status']}] {check['name']}: {check['message']}")
            if check["next_step"]:
                print(f"  Next: {check['next_step']}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
