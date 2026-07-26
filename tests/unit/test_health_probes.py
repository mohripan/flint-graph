"""Readiness must fail on required dependencies and tolerate optional ones."""

from __future__ import annotations

import asyncio

import pytest

from flint_graph.application.services.health_probes import (
    DependencyStatus,
    ReadinessChecker,
    ReadinessStatus,
    report_payload,
)
from flint_graph.config import Settings

pytestmark = pytest.mark.anyio


def _settings(**overrides: object) -> Settings:
    return Settings(env="test", **overrides)  # type: ignore[arg-type]


async def _ok(_session: object, _settings: Settings) -> str | None:
    return None


async def _down(_session: object, _settings: Settings) -> str | None:
    raise ConnectionRefusedError("connection refused")


async def _slow(_session: object, _settings: Settings) -> str | None:
    await asyncio.sleep(5)
    return None


async def test_all_required_dependencies_healthy_is_ready() -> None:
    checker = ReadinessChecker(
        _settings(readiness_required_dependencies=["postgres", "neo4j"]),
        probes={"postgres": _ok, "neo4j": _ok},
    )

    report = await checker.check(session=None)  # type: ignore[arg-type]

    assert report.status is ReadinessStatus.READY
    assert report.http_status_code == 200
    assert [dependency.name for dependency in report.dependencies] == ["postgres", "neo4j"]


async def test_failed_required_dependency_makes_readiness_unavailable() -> None:
    checker = ReadinessChecker(
        _settings(readiness_required_dependencies=["postgres", "neo4j"]),
        probes={"postgres": _ok, "neo4j": _down},
    )

    report = await checker.check(session=None)  # type: ignore[arg-type]

    assert report.status is ReadinessStatus.UNAVAILABLE
    assert report.http_status_code == 503
    assert [dependency.name for dependency in report.failed_required()] == ["neo4j"]
    payload = report_payload(report)
    assert payload["dependencies"]["neo4j"]["status"] == "unavailable"
    assert "connection refused" in payload["dependencies"]["neo4j"]["detail"]


async def test_failed_optional_dependency_is_degraded_but_still_serving() -> None:
    """A provider outage should alert, not remove working capacity."""
    checker = ReadinessChecker(
        _settings(
            readiness_required_dependencies=["postgres"],
            readiness_optional_dependencies=["answer_provider"],
        ),
        probes={"postgres": _ok, "answer_provider": _down},
    )

    report = await checker.check(session=None)  # type: ignore[arg-type]

    assert report.status is ReadinessStatus.DEGRADED
    assert report.http_status_code == 200
    assert report.failed_required() == ()


async def test_probe_exceeding_its_timeout_is_reported_as_timeout() -> None:
    checker = ReadinessChecker(
        _settings(
            readiness_required_dependencies=["postgres"],
            readiness_probe_timeout_seconds=0.01,
        ),
        probes={"postgres": _slow},
    )

    report = await checker.check(session=None)  # type: ignore[arg-type]

    assert report.dependencies[0].status is DependencyStatus.TIMEOUT
    assert report.status is ReadinessStatus.UNAVAILABLE


async def test_results_are_cached_so_polling_does_not_amplify_probes() -> None:
    calls = 0

    async def counting(_session: object, _settings: Settings) -> str | None:
        nonlocal calls
        calls += 1
        return None

    clock = 100.0
    checker = ReadinessChecker(
        _settings(
            readiness_required_dependencies=["postgres"],
            readiness_cache_seconds=5.0,
        ),
        probes={"postgres": counting},
        clock=lambda: clock,
    )

    await checker.check(session=None)  # type: ignore[arg-type]
    await checker.check(session=None)  # type: ignore[arg-type]
    assert calls == 1

    clock += 6.0
    await checker.check(session=None)  # type: ignore[arg-type]
    assert calls == 2


async def test_unprobeable_optional_dependency_does_not_make_readiness_degraded() -> None:
    """Hosted provider APIs have no cheap health surface.

    Reporting them as degraded forever would make the degraded state meaningless,
    so `unknown` is reported per-dependency without changing the verdict.
    """
    checker = ReadinessChecker(
        _settings(
            readiness_required_dependencies=["postgres"],
            readiness_optional_dependencies=["answer_provider"],
            query_answer_provider="anthropic",
            anthropic_api_key="test-key",
        ),
    )

    report = await checker.check(session=_FakeSession())  # type: ignore[arg-type]

    provider = next(
        dependency for dependency in report.dependencies if dependency.name == "answer_provider"
    )
    assert provider.status is DependencyStatus.UNKNOWN
    assert "no health probe" in (provider.detail or "")
    assert report.status is ReadinessStatus.READY
    assert report.http_status_code == 200


class _FakeSession:
    async def execute(self, *_args: object, **_kwargs: object) -> None:
        return None


async def test_unregistered_dependency_is_reported_as_unknown_not_healthy() -> None:
    checker = ReadinessChecker(
        _settings(readiness_required_dependencies=["postgres"]),
        probes={},
    )

    report = await checker.check(session=None)  # type: ignore[arg-type]

    assert report.dependencies[0].status is DependencyStatus.UNKNOWN
    assert report.status is ReadinessStatus.UNAVAILABLE


async def test_failure_detail_strips_credentials_from_connection_strings() -> None:
    async def failing_dsn(_session: object, _settings: Settings) -> str | None:
        raise RuntimeError(
            "could not connect to postgresql+asyncpg://flint:hunter2@db:5432/flint"
        )

    checker = ReadinessChecker(
        _settings(readiness_required_dependencies=["postgres"]),
        probes={"postgres": failing_dsn},
    )

    report = await checker.check(session=None)  # type: ignore[arg-type]

    detail = report.dependencies[0].detail or ""
    assert "hunter2" not in detail
    assert "[redacted]@db:5432/flint" in detail


def test_unknown_dependency_names_are_rejected_by_configuration() -> None:
    with pytest.raises(ValueError, match="unknown readiness dependency"):
        _settings(readiness_required_dependencies=["postgres", "mongodb"])


def test_a_dependency_cannot_be_both_required_and_optional() -> None:
    with pytest.raises(ValueError, match="both required and optional"):
        _settings(
            readiness_required_dependencies=["postgres", "neo4j"],
            readiness_optional_dependencies=["neo4j"],
        )


def test_deployed_environments_require_the_full_dependency_set() -> None:
    settings = Settings(
        env="staging",
        public_base_url="https://api.example",
        allowed_origins=["https://app.example"],
        trusted_hosts=["api.example"],
        require_tls=True,
        allow_private_url_intake=False,
        rate_limit_enabled=True,
        allow_in_memory_rate_limit=True,
        auth_mode="oidc",
        oidc_issuer="https://issuer.example/realms/flintgraph",
        oidc_audience="flintgraph-api",
        object_store_access_key_id="real-key",
        object_store_secret_access_key="real-secret",
        embedding_provider="deterministic",
        query_answer_provider="deterministic",
        query_support_provider="deterministic",
    )

    assert settings.readiness_required_dependencies == [
        "postgres",
        "object_store",
        "temporal",
        "neo4j",
        "opensearch",
    ]
    assert settings.readiness_optional_dependencies == [
        "embedding_provider",
        "answer_provider",
    ]
