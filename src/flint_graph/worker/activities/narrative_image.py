"""Image activity edge: prompts and bytes stay here; Temporal history gets IDs/status."""

import asyncio
from contextlib import suppress
from typing import Literal, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio import activity
from temporalio.exceptions import ApplicationError

from flint_graph.application.narrative_image_workflow import (
    FINALIZE_IMAGE_ACTIVITY,
    IMAGE_WORKFLOW,
    RUN_IMAGE_ACTIVITY,
    FinalizeImagePayload,
    ImageJobOutcome,
    ImageJobPayload,
    image_job_workflow_id,
    validate_image_payload,
)
from flint_graph.application.services.narrative_images import (
    ImageRegistrationPending,
    abandon_image_job,
    claim_image_job,
    complete_image_job,
    fail_image_job,
    record_progress,
)
from flint_graph.infrastructure.db.models import NarrativeImageJob
from flint_graph.infrastructure.narrative_artifact_store import (
    ArtifactStoreError,
    asset_object_key,
)
from flint_graph.infrastructure.narrative_imagegen import (
    IMAGE_LIMIT,
    THUMBNAIL_LIMIT,
    GeneratedImage,
    GenerationRequest,
    GenerationResult,
    GpuReleaser,
    ImageGenerationError,
    ImageGenerator,
)

# A busy or exhausted GPU may free up; other failures would repeat identically.
_TRANSIENT = {"gpu_busy", "out_of_memory"}
_TERMINAL = ("completed", "failed", "cancelled")


class ImageStore(Protocol):
    async def put_once(
        self,
        key: str,
        data: bytes,
        *,
        expected_sha256: str,
        content_type: str,
        max_bytes: int,
    ) -> object: ...


class _CancelRequested(Exception):
    pass


def _outcome(job_id: UUID, job: NarrativeImageJob | None) -> ImageJobOutcome:
    status = job.status if job is not None and job.status in _TERMINAL else "stale"
    return cast(ImageJobOutcome, {"job_id": str(job_id), "status": status})


async def _heartbeat() -> None:
    while True:
        activity.heartbeat()
        await asyncio.sleep(5)


class NarrativeImageActivities:
    def __init__(
        self,
        *,
        factory: async_sessionmaker[AsyncSession],
        generator: ImageGenerator | None,
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
                info.workflow_id != image_job_workflow_id(data)
                or info.workflow_type != IMAGE_WORKFLOW
                or info.activity_type
                != (FINALIZE_IMAGE_ACTIVITY if finalizer else RUN_IMAGE_ACTIVITY)
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
            job = await fail_image_job(
                session, job_id=job_id, execution_token=token, error_code=code
            )
            await session.commit()
        return _outcome(job_id, job)

    async def _generate(
        self, generator: ImageGenerator, request: GenerationRequest, job_id: UUID, token: UUID
    ) -> GenerationResult:
        async def progress(done: int) -> None:
            async with self.factory() as session:
                keep = await record_progress(
                    session, job_id=job_id, execution_token=token, progress=done
                )
                await session.commit()
            if not keep:
                raise _CancelRequested

        try:
            return await generator.generate(request, on_progress=progress)
        except ImageGenerationError as error:
            if error.code != "gpu_busy" or self.releaser is None:
                raise
            try:
                await self.releaser.release()
            except Exception:
                raise error from None
            return await generator.generate(request, on_progress=progress)

    async def _store(
        self, work_tenant: UUID, work_project: UUID, images: tuple[GeneratedImage, ...]
    ) -> list[tuple[UUID, GeneratedImage]]:
        stored = []
        for image in images:
            asset_id = uuid4()
            for variant, data, digest, limit in (
                ("image", image.data, image.sha256, IMAGE_LIMIT),
                ("thumbnail", image.thumbnail, image.thumbnail_sha256, THUMBNAIL_LIMIT),
            ):
                key = asset_object_key(
                    tenant_id=work_tenant,
                    project_id=work_project,
                    asset_id=asset_id,
                    variant=cast(Literal["image", "thumbnail"], variant),
                )
                await self.store.put_once(
                    key, data, expected_sha256=digest, content_type="image/png", max_bytes=limit
                )
            stored.append((asset_id, image))
        return stored

    @activity.defn(name=RUN_IMAGE_ACTIVITY)
    async def run(self, payload: ImageJobPayload) -> ImageJobOutcome:
        data, run_id, attempt = self._context(payload)
        job_id, token = UUID(data["job_id"]), uuid4()
        try:
            async with self.factory() as session:
                work = await claim_image_job(
                    session,
                    job_id=job_id,
                    execution_token=token,
                    workflow_run_id=run_id,
                    activity_attempt=attempt,
                )
                await session.commit()
        except ImageRegistrationPending:
            raise ApplicationError("registration_pending", type="registration_pending") from None
        if work is None:
            return _outcome(job_id, None)
        if self.generator is None:
            return await self._fail(job_id, token, "image_generation_unavailable")
        generator = self.generator
        beating = asyncio.create_task(_heartbeat())
        try:
            result = await self._generate(generator, work.request, job_id, token)
            stored = await self._store(work.tenant_id, work.project_id, result.images)
        except ImageGenerationError as error:
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
            job = await complete_image_job(
                session,
                job_id=job_id,
                execution_token=token,
                result=result,
                stored=stored,
                model=generator.model,
            )
            await session.commit()
        return _outcome(job_id, job)

    @activity.defn(name=FINALIZE_IMAGE_ACTIVITY)
    async def finalize(self, payload: FinalizeImagePayload) -> ImageJobOutcome:
        cancelled = payload.get("cancelled") if isinstance(payload, dict) else None
        if type(cancelled) is not bool:
            raise ApplicationError("activity_identity", non_retryable=True)
        base = {key: value for key, value in payload.items() if key != "cancelled"}
        data, run_id, _ = self._context(base, finalizer=True)
        job_id = UUID(data["job_id"])
        async with self.factory() as session:
            job = await abandon_image_job(
                session,
                job_id=job_id,
                workflow_run_id=run_id,
                error_code="cancelled" if cancelled else "worker_interrupted",
            )
            await session.commit()
        return _outcome(job_id, job)
