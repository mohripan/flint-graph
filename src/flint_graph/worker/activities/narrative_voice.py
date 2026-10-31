"""Voice activity edge (ADR 0043): texts and clips stay here; history gets IDs and status."""

import asyncio
from contextlib import suppress
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio import activity
from temporalio.exceptions import ApplicationError

from flint_graph.application.narrative_image_workflow import (
    FINALIZE_VOICE_ACTIVITY,
    RUN_VOICE_ACTIVITY,
    VOICE_WORKFLOW,
    FinalizeImagePayload,
    ImageJobOutcome,
    ImageJobPayload,
    validate_image_payload,
    voice_job_workflow_id,
)
from flint_graph.application.services.narrative_voices import (
    VoiceRegistrationPending,
    abandon_voice_job,
    claim_voice_job,
    complete_voice_job,
    fail_voice_job,
    record_voice_progress,
)
from flint_graph.infrastructure.db.models import NarrativeVoiceJob
from flint_graph.infrastructure.narrative_artifact_store import (
    ArtifactStoreError,
    asset_object_key,
)
from flint_graph.infrastructure.narrative_voicegen import (
    GeneratedClip,
    VoiceGenerationError,
    VoiceGenerator,
    VoiceRequest,
    VoiceResult,
)
from flint_graph.narrative.wav import AUDIO_LIMIT
from flint_graph.worker.activities.narrative_image import ImageStore

_TERMINAL = ("completed", "failed", "cancelled")


class _CancelRequested(Exception):
    pass


def _outcome(job_id: UUID, job: NarrativeVoiceJob | None) -> ImageJobOutcome:
    status = job.status if job is not None and job.status in _TERMINAL else "stale"
    return cast(ImageJobOutcome, {"job_id": str(job_id), "status": status})


async def _heartbeat() -> None:
    while True:
        activity.heartbeat()
        await asyncio.sleep(5)


class NarrativeVoiceActivities:
    def __init__(
        self,
        *,
        factory: async_sessionmaker[AsyncSession],
        generator: VoiceGenerator | None,
        store: ImageStore,
    ) -> None:
        self.factory, self.generator, self.store = factory, generator, store

    @staticmethod
    def _context(payload: object, *, finalizer: bool = False) -> tuple[ImageJobPayload, UUID, int]:
        try:
            data = validate_image_payload(payload)
            info = activity.info()
            run_id = UUID(info.workflow_run_id or "")
            if (
                info.workflow_id != voice_job_workflow_id(data)
                or info.workflow_type != VOICE_WORKFLOW
                or info.activity_type
                != (FINALIZE_VOICE_ACTIVITY if finalizer else RUN_VOICE_ACTIVITY)
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
            job = await fail_voice_job(
                session, job_id=job_id, execution_token=token, error_code=code
            )
            await session.commit()
        return _outcome(job_id, job)

    async def _generate(
        self, generator: VoiceGenerator, request: VoiceRequest, job_id: UUID, token: UUID
    ) -> VoiceResult:
        async def progress(done: int) -> None:
            async with self.factory() as session:
                keep = await record_voice_progress(
                    session, job_id=job_id, execution_token=token, progress=done
                )
                await session.commit()
            if not keep:
                raise _CancelRequested

        return await generator.generate(request, on_progress=progress)

    async def _store(
        self, tenant_id: UUID, project_id: UUID, clips: tuple[GeneratedClip, ...]
    ) -> list[tuple[UUID, GeneratedClip]]:
        stored = []
        for clip in clips:
            asset_id = uuid4()
            await self.store.put_once(
                asset_object_key(
                    tenant_id=tenant_id, project_id=project_id, asset_id=asset_id, variant="audio"
                ),
                clip.data,
                expected_sha256=clip.sha256,
                content_type="audio/wav",
                max_bytes=AUDIO_LIMIT,
            )
            stored.append((asset_id, clip))
        return stored

    @activity.defn(name=RUN_VOICE_ACTIVITY)
    async def run(self, payload: ImageJobPayload) -> ImageJobOutcome:
        data, run_id, attempt = self._context(payload)
        job_id, token = UUID(data["job_id"]), uuid4()
        try:
            async with self.factory() as session:
                work = await claim_voice_job(
                    session,
                    job_id=job_id,
                    execution_token=token,
                    workflow_run_id=run_id,
                    activity_attempt=attempt,
                )
                await session.commit()
        except VoiceRegistrationPending:
            raise ApplicationError("registration_pending", type="registration_pending") from None
        if work is None:
            return _outcome(job_id, None)
        if self.generator is None:
            return await self._fail(job_id, token, "voice_generation_unavailable")
        generator = self.generator
        beating = asyncio.create_task(_heartbeat())
        try:
            result = await self._generate(generator, work.request, job_id, token)
            stored = await self._store(work.tenant_id, work.project_id, result.clips)
        except VoiceGenerationError as error:
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
            job = await complete_voice_job(
                session,
                job_id=job_id,
                execution_token=token,
                result=result,
                stored=stored,
                model=generator.model,
            )
            await session.commit()
        return _outcome(job_id, job)

    @activity.defn(name=FINALIZE_VOICE_ACTIVITY)
    async def finalize(self, payload: FinalizeImagePayload) -> ImageJobOutcome:
        cancelled = payload.get("cancelled") if isinstance(payload, dict) else None
        if type(cancelled) is not bool:
            raise ApplicationError("activity_identity", non_retryable=True)
        base = {key: value for key, value in payload.items() if key != "cancelled"}
        data, run_id, _ = self._context(base, finalizer=True)
        job_id = UUID(data["job_id"])
        async with self.factory() as session:
            job = await abandon_voice_job(
                session,
                job_id=job_id,
                workflow_run_id=run_id,
                error_code="cancelled" if cancelled else "worker_interrupted",
            )
            await session.commit()
        return _outcome(job_id, job)
