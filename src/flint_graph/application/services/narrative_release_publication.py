"""Atomic metadata publication after private immutable object verification.

No network work runs under release/job locks. Receipts must come from the trusted
store adapter; the service independently binds their keys, sizes, hashes and manifest.
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.narrative_release_state import ReleaseJobStatus, finish_execution
from flint_graph.application.services.narrative_release_execution import (
    append_execution_event,
    lock_release_execution,
    release_attempt,
)
from flint_graph.domain.errors import DomainError
from flint_graph.infrastructure.db.models import (
    NarrativeRelease,
    NarrativeReleaseArtifact,
    NarrativeReleaseJob,
)
from flint_graph.infrastructure.narrative_artifact_store import ObjectReceipt, release_artifact_key
from flint_graph.narrative.values import canonical_json

Kind = Literal["source", "web", "manifest"]
KINDS: tuple[Kind, ...] = ("source", "web", "manifest")


def artifact_filename(release_id: UUID, kind: Kind) -> str:
    return f"game-{release_id.hex}-{kind}." + ("json" if kind == "manifest" else "zip")


def _valid_receipt(receipt: ObjectReceipt, kind: Kind) -> bool:
    cap = 1048576 if kind == "manifest" else 67108864
    return (
        type(receipt.size_bytes) is int
        and 1 <= receipt.size_bytes <= cap
        and isinstance(receipt.sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", receipt.sha256) is not None
    )


def make_release_manifest(
    release: NarrativeRelease,
    *,
    job_id: UUID,
    source: ObjectReceipt,
    web: ObjectReceipt,
) -> bytes:
    if not _valid_receipt(source, "source") or not _valid_receipt(web, "web"):
        raise ValueError("Invalid release artifact metadata")
    entries: tuple[tuple[Kind, ObjectReceipt], ...] = (("source", source), ("web", web))
    return canonical_json(
        {
            "schema_version": "1",
            "release_id": str(release.id),
            "revision_id": str(release.revision_id),
            "job_id": str(job_id),
            "package_hash": release.package_hash,
            "compiler_version": release.compiler_version,
            "runtime_version": release.runtime_version,
            "godot_version": release.godot_version,
            "toolchain_sha256": release.toolchain_sha256,
            "builder_image_digest": release.builder_image_digest,
            "artifacts": {
                kind: {
                    "sha256": receipt.sha256,
                    "size_bytes": receipt.size_bytes,
                    "media_type": "application/zip",
                    "filename": artifact_filename(release.id, kind),
                }
                for kind, receipt in entries
            },
        }
    )


async def published_artifacts(
    session: AsyncSession,
    release: NarrativeRelease,
    job: NarrativeReleaseJob,
) -> list[NarrativeReleaseArtifact]:
    if job.status != "completed":
        return []
    rows = list(
        await session.scalars(
            select(NarrativeReleaseArtifact)
            .where(
                NarrativeReleaseArtifact.tenant_id == release.tenant_id,
                NarrativeReleaseArtifact.project_id == release.project_id,
                NarrativeReleaseArtifact.release_id == release.id,
                NarrativeReleaseArtifact.job_id == job.id,
            )
            .order_by(NarrativeReleaseArtifact.kind)
        )
    )
    tokens = set()
    try:
        if len(rows) != 3 or {row.kind for row in rows} != set(KINDS):
            raise ValueError
        for row in rows:
            if row.kind not in KINDS:
                raise ValueError
            kind: Kind = row.kind
            token = UUID(row.object_key.split("/executions/")[1].split("/")[0])
            expected = release_artifact_key(
                tenant_id=release.tenant_id,
                release_id=release.id,
                job_id=job.id,
                execution_token=token,
                kind=kind,
            )
            if (
                row.object_key != expected
                or not _valid_receipt(
                    ObjectReceipt(row.object_key, row.sha256, row.size_bytes), kind
                )
                or row.filename != artifact_filename(release.id, kind)
                or row.media_type
                != ("application/json" if kind == "manifest" else "application/zip")
            ):
                raise ValueError
            tokens.add(token)
        if len(tokens) != 1 or sum(row.size_bytes for row in rows) > 134217728:
            raise ValueError
    except (ValueError, IndexError):
        raise DomainError(
            503,
            "Service unavailable",
            "Release artifacts are unavailable.",
            "release-artifacts-unavailable",
        ) from None
    return sorted(rows, key=lambda row: KINDS.index(row.kind))


@dataclass(frozen=True)
class PublicationResult:
    status: Literal["completed", "cancelled", "stale"]
    changed: bool
    artifact_ids: tuple[UUID, ...] = ()


async def publish_release_artifacts(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    release_id: UUID,
    job_id: UUID,
    token: UUID,
    receipts: Mapping[str, ObjectReceipt],
    manifest_json: bytes,
) -> PublicationResult:
    release, job, active_id = await lock_release_execution(session, tenant_id, release_id, job_id)
    before = release_attempt(job)
    after = finish_execution(before, token=token, active_job_id=active_id, outcome="completed")
    if before == after:
        if before.status == ReleaseJobStatus.COMPLETED and active_id == job_id:
            rows = await published_artifacts(session, release, job)
            return PublicationResult("completed", False, tuple(row.id for row in rows))
        return PublicationResult("stale", False)
    if after.status == ReleaseJobStatus.CANCELLED:
        job.status, job.execution_token, job.cancel_requested = "cancelled", None, True
        job.finished_at, job.error_code = datetime.now(UTC), None
        append_execution_event(session, job, "release.cancelled")
        await session.flush()
        return PublicationResult("cancelled", True)
    if set(receipts) != set(KINDS) or any(
        not _valid_receipt(receipts[kind], kind) for kind in KINDS
    ):
        raise ValueError("Invalid release artifact metadata")
    for kind in KINDS:
        if receipts[kind].key != release_artifact_key(
            tenant_id=tenant_id,
            release_id=release_id,
            job_id=job_id,
            execution_token=token,
            kind=kind,
        ):
            raise ValueError("Invalid release artifact metadata")
    expected_manifest = make_release_manifest(
        release, job_id=job_id, source=receipts["source"], web=receipts["web"]
    )
    manifest = receipts["manifest"]
    if (
        manifest_json != expected_manifest
        or manifest.size_bytes != len(manifest_json)
        or manifest.sha256 != hashlib.sha256(manifest_json).hexdigest()
        or sum(receipt.size_bytes for receipt in receipts.values()) > 134217728
        or await session.scalar(
            select(NarrativeReleaseArtifact.id)
            .where(
                NarrativeReleaseArtifact.release_id == release_id,
                NarrativeReleaseArtifact.tenant_id == tenant_id,
            )
            .limit(1)
        )
        is not None
    ):
        raise ValueError("Invalid release artifact metadata")
    identifiers = []
    for kind in KINDS:
        receipt = receipts[kind]
        identifier = uuid4()
        identifiers.append(identifier)
        session.add(
            NarrativeReleaseArtifact(
                id=identifier,
                tenant_id=tenant_id,
                project_id=release.project_id,
                release_id=release_id,
                job_id=job_id,
                kind=kind,
                object_key=receipt.key,
                sha256=receipt.sha256,
                size_bytes=receipt.size_bytes,
                filename=artifact_filename(release_id, kind),
                media_type="application/json" if kind == "manifest" else "application/zip",
            )
        )
    job.status, job.execution_token, job.error_code = "completed", None, None
    job.finished_at = datetime.now(UTC)
    append_execution_event(session, job, "release.completed")
    await session.flush()
    return PublicationResult("completed", True, tuple(identifiers))
