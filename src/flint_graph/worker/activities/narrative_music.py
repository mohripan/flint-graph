"""Music activity edge (ADR 0067): descriptions and audio stay here.

Temporal history gets IDs and status only.
"""

import asyncio
from contextlib import suppress
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio import activity
from temporalio.exceptions import ApplicationError

from flint_graph.application.narrative_image_workflow import (
    FINALIZE_MUSIC_ACTIVITY,
    MUSIC_WORKFLOW,
    RUN_MUSIC_ACTIVITY,
    FinalizeImagePayload,
    ImageJobOutcome,
    ImageJobPayload,
    music_job_workflow_id,
    validate_image_payload,
)
from flint_graph.application.services.narrative_music import (
    MusicRegistrationPending,
    abandon_music_job,
    claim_music_job,
    complete_music_job,
    fail_music_job,
    record_music_progress,
)
from flint_graph.infrastructure.db.models import NarrativeMusicJob
from flint_graph.infrastructure.narrative_artifact_store import (
    ArtifactStoreError,
    asset_object_key,
)
from flint_graph.infrastructure.narrative_imagegen import GpuReleaser
from flint_graph.infrastructure.narrative_musicgen import (
    MusicGenerationError,
    MusicGenerator,
    MusicRequest,
    MusicResult,
)
from flint_graph.narrative.ogg import MUSIC_LIMIT
from flint_graph.worker.activities.narrative_image import ImageStore

# A busy GPU may free up (image jobs or the assistant's model finish); other failures
# would repeat identically.
_TRANSIENT = {"gpu_busy"}
_TERMINAL = ("completed", "failed", "cancelled")


class _CancelRequested(Exception):
    pass


def _outcome(job_id: UUID, job: NarrativeMusicJob | None) -> ImageJobOutcome:
    status = job.status if job is not None and job.status in _TERMINAL else "stale"
    return cast(ImageJobOutcome, {"job_id": str(job_id), "status": status})


async def _heartbeat() -> None:
    while True:
        activity.heartbeat()
        await asyncio.sleep(5)


class NarrativeMusicActivities:
    def __init__(
        self,
        *,
        factory: async_sessionmaker[AsyncSession],
        generator: MusicGenerator,
        store: ImageStore,
        releaser: GpuReleaser | None = None,
        max_attempts: int = 3,
    ) -> None:
        self.factory, self.generator, self.store = factory, generator, store
        self.releaser, self.max_attempts = releaser, max_attempts

    @staticmethod
    def _context(payload: object, *, finalizer: bool = False) -> tuple[ImageJobPayload, UUID, int]:
        try:
            data = validate_image_payload(payload)
            info = activity.info()
            run_id = UUID(info.workflow_run_id or "")
            if (
                info.workflow_id != music_job_workflow_id(data)
                or info.workflow_type != MUSIC_WORKFLOW
                or info.activity_type
                != (FINALIZE_MUSIC_ACTIVITY if finalizer else RUN_MUSIC_ACTIVITY)
                or info.is_local
                or type(info.attempt) is not int
                or info.attempt < 1
                or str(run_id) != info.workflow_run_id
            ):
                raise ValueError
            return data, run_id, info.attempt
        except Exception:
            raise ApplicationError("activity_identity", non_retryable=True) from None

    async def _fail(self, job_id: UUID, token: UUID, code: str) -> ImageJobOutcome:
        async with self.factory() as session:
            job = await fail_music_job(
                session, job_id=job_id, execution_token=token, error_code=code
            )
            await session.commit()
        return _outcome(job_id, job)

    async def _generate(self, request: MusicRequest, job_id: UUID, token: UUID) -> MusicResult:
        async def progress(done: int) -> None:
            async with self.factory() as session:
                keep = await record_music_progress(
                    session, job_id=job_id, execution_token=token, progress=done
                )
                await session.commit()
            if not keep:
                raise _CancelRequested

        try:
            return await self.generator.generate(request, on_progress=progress)
        except MusicGenerationError as error:
            if error.code != "gpu_busy" or self.releaser is None:
                raise
            try:
                await self.releaser.release()
            except Exception:
                raise error from None
            return await self.generator.generate(request, on_progress=progress)

    @activity.defn(name=RUN_MUSIC_ACTIVITY)
    async def run(self, payload: ImageJobPayload) -> ImageJobOutcome:
        data, run_id, attempt = self._context(payload)
        job_id, token = UUID(data["job_id"]), uuid4()
        try:
            async with self.factory() as session:
                work = await claim_music_job(
                    session,
                    job_id=job_id,
                    execution_token=token,
                    workflow_run_id=run_id,
                    activity_attempt=attempt,
                )
                await session.commit()
        except MusicRegistrationPending:
            raise ApplicationError("registration_pending", type="registration_pending") from None
        if work is None:
            return _outcome(job_id, None)
        asset_id = uuid4()
        beating = asyncio.create_task(_heartbeat())
        try:
            result = await self._generate(work.request, job_id, token)
            await self.store.put_once(
                asset_object_key(
                    tenant_id=work.tenant_id,
                    project_id=work.project_id,
                    asset_id=asset_id,
                    variant="music",
                ),
                result.track.data,
                expected_sha256=result.track.sha256,
                content_type="audio/ogg",
                max_bytes=MUSIC_LIMIT,
            )
        except MusicGenerationError as error:
            if error.code in _TRANSIENT and attempt < self.max_attempts:
                # The job stays running; the next attempt of this run replaces the token.
                raise ApplicationError(error.code, type=error.code) from None
            return await self._fail(job_id, token, error.code)
        except _CancelRequested:
            return await self._fail(job_id, token, "cancelled")
        except ArtifactStoreError:
            return await self._fail(job_id, token, "storage_unavailable")
        except asyncio.CancelledError:
            cleanup = asyncio.create_task(self._fail(job_id, token, "cancelled"))
            while not cleanup.done():
                with suppress(asyncio.CancelledError):
                    await asyncio.shield(cleanup)
            raise
        except Exception:
            return await self._fail(job_id, token, "generation_failed")
        finally:
            beating.cancel()
            with suppress(asyncio.CancelledError):
                await beating
        async with self.factory() as session:
            job = await complete_music_job(
                session,
                job_id=job_id,
                execution_token=token,
                result=result,
                asset_id=asset_id,
                model=self.generator.model,
            )
            await session.commit()
        return _outcome(job_id, job)

    @activity.defn(name=FINALIZE_MUSIC_ACTIVITY)
    async def finalize(self, payload: FinalizeImagePayload) -> ImageJobOutcome:
        cancelled = payload.get("cancelled") if isinstance(payload, dict) else None
        if type(cancelled) is not bool:
            raise ApplicationError("activity_identity", non_retryable=True)
        base = {key: value for key, value in payload.items() if key != "cancelled"}
        data, run_id, _ = self._context(base, finalizer=True)
        job_id = UUID(data["job_id"])
        async with self.factory() as session:
            job = await abandon_music_job(
                session,
                job_id=job_id,
                workflow_run_id=run_id,
                error_code="cancelled" if cancelled else "worker_interrupted",
            )
            await session.commit()
        return _outcome(job_id, job)
