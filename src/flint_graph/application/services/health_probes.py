"""Readiness dependency probes.

``/health/ready`` answers one question: should this replica receive traffic?
Before Milestone 14 it only ran ``SELECT 1``, so Neo4j, OpenSearch, MinIO, and
Temporal could all be down while readiness reported ``ready``.

Required dependencies fail readiness. Optional ones are probed and reported but
keep the replica in service, because pulling capacity for a degraded model
provider makes an outage worse, not better.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.config import Settings
from flint_graph.observability import metrics
from flint_graph.observability.instruments import READINESS_PROBE_DURATION


class DependencyStatus(StrEnum):
    OK = "ok"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    # A dependency with no cheap health surface (a hosted LLM API, for example).
    # Reported honestly rather than assumed healthy.
    UNKNOWN = "unknown"


class ReadinessStatus(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class DependencyResult:
    name: str
    status: DependencyStatus
    required: bool
    duration_ms: float
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    status: ReadinessStatus
    dependencies: tuple[DependencyResult, ...]

    @property
    def http_status_code(self) -> int:
        return 200 if self.status is not ReadinessStatus.UNAVAILABLE else 503

    def failed_required(self) -> tuple[DependencyResult, ...]:
        return tuple(
            dependency
            for dependency in self.dependencies
            if dependency.required and dependency.status is not DependencyStatus.OK
        )


class BucketChecker(Protocol):
    async def check_bucket(self, bucket: str) -> None: ...


Probe = Callable[[AsyncSession, Settings], Awaitable[str | None]]


async def _probe_postgres(session: AsyncSession, _settings: Settings) -> str | None:
    await session.execute(text("SELECT 1"))
    return None


async def _probe_object_store(_session: AsyncSession, settings: Settings) -> str | None:
    from flint_graph.infrastructure.object_store import create_s3_object_store

    store = create_s3_object_store(settings)
    await store.check_bucket(settings.object_store_bucket)
    return f"bucket '{settings.object_store_bucket}' reachable"


async def _probe_temporal(_session: AsyncSession, settings: Settings) -> str | None:
    from flint_graph.infrastructure.temporal import connect_temporal

    client = await connect_temporal(settings)
    await client.service_client.check_health()
    return f"namespace '{settings.temporal_namespace}'"


async def _probe_neo4j(_session: AsyncSession, settings: Settings) -> str | None:
    from flint_graph.infrastructure.neo4j import create_neo4j_client

    client = create_neo4j_client(settings)
    try:
        await client.execute("RETURN 1 AS ok")
    finally:
        await client.close()
    return None


async def _probe_opensearch(_session: AsyncSession, settings: Settings) -> str | None:
    from flint_graph.infrastructure.opensearch import create_opensearch_client

    client = create_opensearch_client(settings)
    try:
        await client.check_cluster()
    finally:
        await client.close()
    return None


async def _probe_embedding_provider(
    _session: AsyncSession, settings: Settings
) -> str | None:
    provider = settings.embedding_provider or "deterministic"
    if provider == "deterministic":
        return "deterministic provider needs no network"
    if provider == "ollama":
        await _probe_ollama(settings.embedding_ollama_base_url)
        return f"ollama at {settings.embedding_ollama_base_url}"
    raise _NoHealthSurface(f"no health probe for embedding provider '{provider}'")


async def _probe_answer_provider(_session: AsyncSession, settings: Settings) -> str | None:
    provider = settings.query_answer_provider or "deterministic"
    if provider == "deterministic":
        return "deterministic provider needs no network"
    if provider == "ollama":
        await _probe_ollama(settings.ollama_base_url)
        return f"ollama at {settings.ollama_base_url}"
    raise _NoHealthSurface(f"no health probe for answer provider '{provider}'")


class _NoHealthSurface(Exception):
    """Raised when a dependency cannot be probed cheaply and honestly."""


async def _probe_ollama(base_url: str) -> None:
    async with httpx.AsyncClient(base_url=base_url) as client:
        response = await client.get("/api/tags")
        response.raise_for_status()


PROBES: dict[str, Probe] = {
    "postgres": _probe_postgres,
    "object_store": _probe_object_store,
    "temporal": _probe_temporal,
    "neo4j": _probe_neo4j,
    "opensearch": _probe_opensearch,
    "embedding_provider": _probe_embedding_provider,
    "answer_provider": _probe_answer_provider,
}


class ReadinessChecker:
    """Runs dependency probes with a timeout and a short result cache.

    Caching matters: liveness/readiness endpoints are polled by every load
    balancer and orchestrator in the path, and an uncached probe set turns that
    polling into load on the dependencies it is meant to protect.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        probes: dict[str, Probe] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._probes = probes if probes is not None else PROBES
        self._clock = clock
        self._cached: ReadinessReport | None = None
        self._cached_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def settings(self) -> Settings:
        return self._settings

    async def check(self, session: AsyncSession) -> ReadinessReport:
        async with self._lock:
            cached = self._cached
            if (
                cached is not None
                and self._settings.readiness_cache_seconds > 0
                and (self._clock() - self._cached_at)
                < self._settings.readiness_cache_seconds
            ):
                return cached

            report = await self._run(session)
            self._cached = report
            self._cached_at = self._clock()
            return report

    def invalidate(self) -> None:
        self._cached = None

    async def _run(self, session: AsyncSession) -> ReadinessReport:
        required = list(self._settings.readiness_required_dependencies or [])
        optional = [
            name
            for name in (self._settings.readiness_optional_dependencies or [])
            if name not in required
        ]
        results: list[DependencyResult] = []
        for name in [*required, *optional]:
            results.append(
                await self._run_probe(
                    session,
                    name=name,
                    required=name in required,
                )
            )
        return ReadinessReport(status=_overall_status(results), dependencies=tuple(results))

    async def _run_probe(
        self,
        session: AsyncSession,
        *,
        name: str,
        required: bool,
    ) -> DependencyResult:
        probe = self._probes.get(name)
        started = self._clock()
        if probe is None:
            return DependencyResult(
                name=name,
                status=DependencyStatus.UNKNOWN,
                required=required,
                duration_ms=0.0,
                detail="no probe is registered for this dependency",
            )

        status = DependencyStatus.OK
        detail: str | None = None
        try:
            detail = await asyncio.wait_for(
                probe(session, self._settings),
                timeout=self._settings.readiness_probe_timeout_seconds,
            )
        except TimeoutError:
            status = DependencyStatus.TIMEOUT
            detail = (
                f"probe exceeded {self._settings.readiness_probe_timeout_seconds:g}s"
            )
        except _NoHealthSurface as exc:
            status = DependencyStatus.UNKNOWN
            detail = str(exc)
        except Exception as exc:
            status = DependencyStatus.UNAVAILABLE
            detail = _failure_detail(exc)

        duration_ms = (self._clock() - started) * 1000
        metrics.record(
            READINESS_PROBE_DURATION,
            duration_ms,
            **{"flint_graph.dependency": name, "flint_graph.dependency.status": status},
        )
        return DependencyResult(
            name=name,
            status=status,
            required=required,
            duration_ms=round(duration_ms, 3),
            detail=detail,
        )


def _overall_status(results: list[DependencyResult]) -> ReadinessStatus:
    """Roll per-dependency results into one status.

    ``unknown`` on an optional dependency is the steady state for hosted provider
    APIs, which have no cheap health surface. Treating that as ``degraded`` would
    make degraded permanent and teach operators to ignore it, so it is reported
    per-dependency without changing the overall verdict. A required dependency
    that cannot be verified still fails: unverifiable is not ready.
    """
    if any(
        result.required and result.status is not DependencyStatus.OK for result in results
    ):
        return ReadinessStatus.UNAVAILABLE
    if any(
        result.status in {DependencyStatus.UNAVAILABLE, DependencyStatus.TIMEOUT}
        for result in results
    ):
        return ReadinessStatus.DEGRADED
    return ReadinessStatus.READY


def _failure_detail(exc: Exception) -> str:
    """Describe a failure without echoing credentials from connection strings."""
    message = str(exc).strip() or exc.__class__.__name__
    redacted = _redact_credentials(message)
    return f"{exc.__class__.__name__}: {redacted}"[:500]


def _redact_credentials(message: str) -> str:
    # Driver errors habitually include the DSN, and a DSN habitually includes a
    # password. Readiness output is unauthenticated, so strip userinfo.
    parts: list[str] = []
    for token in message.split():
        if "://" in token and "@" in token:
            scheme, _, remainder = token.partition("://")
            _, _, host = remainder.rpartition("@")
            parts.append(f"{scheme}://[redacted]@{host}")
        else:
            parts.append(token)
    return " ".join(parts)


def report_payload(report: ReadinessReport) -> dict[str, Any]:
    return {
        "status": report.status.value,
        "dependencies": {
            dependency.name: {
                "status": dependency.status.value,
                "required": dependency.required,
                "duration_ms": dependency.duration_ms,
                **({"detail": dependency.detail} if dependency.detail else {}),
            }
            for dependency in report.dependencies
        },
    }
