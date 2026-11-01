"""Fenced private training. Temporal receives IDs and terminal status only."""

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio import activity
from temporalio.exceptions import ApplicationError

from flint_graph.application.narrative_image_workflow import (
    ImageJobOutcome,
    ImageJobPayload,
    validate_image_payload,
)
from flint_graph.application.services.narrative_character_adapters import details, verify_target
from flint_graph.application.services.narrative_styles import (
    ACTIVE,
    RECIPE_SHA,
    WORKFLOW,
    workflow_id,
)
from flint_graph.domain.errors import DomainError
from flint_graph.infrastructure.db.models import NarrativeAsset
from flint_graph.infrastructure.db.narrative_style_models import NarrativeStyleJob
from flint_graph.infrastructure.narrative_artifact_store import asset_object_key
from flint_graph.infrastructure.narrative_model_tracking import ModelTracker
from flint_graph.infrastructure.narrative_stylegen import StyleTrainingRequest, StyleTrainingResult
from flint_graph.narrative.style_weights import validate_adapter


class StyleStore(Protocol):
    async def put_private_adapter(
        self, key: str, data: bytes, *, expected_sha256: str
    ) -> object: ...
    async def get_verified(
        self, key: str, *, expected_size: int, expected_sha256: str, max_bytes: int
    ) -> bytes: ...


class StyleTrainer(Protocol):
    model_hash: str

    async def train(
        self, request: StyleTrainingRequest, *, on_progress: Any
    ) -> StyleTrainingResult: ...


class Superseded(Exception):
    pass


def outcome(row: NarrativeStyleJob) -> ImageJobOutcome:
    return cast(
        ImageJobOutcome,
        {"job_id": str(row.id), "status": row.status if row.status not in ACTIVE else "stale"},
    )


class NarrativeStyleActivities:
    def __init__(
        self,
        *,
        factory: async_sessionmaker[AsyncSession],
        trainer: StyleTrainer,
        store: StyleStore,
        tracker: ModelTracker | None = None,
    ) -> None:
        self.factory, self.trainer, self.store, self.tracker = factory, trainer, store, tracker

    def context(
        self, payload: object, *, finalizer: bool = False
    ) -> tuple[ImageJobPayload, UUID, int]:
        try:
            data = validate_image_payload(payload)
            info = activity.info()
            run_id = UUID(info.workflow_run_id or "")
            if (
                info.workflow_id != workflow_id(data)
                or info.workflow_type != WORKFLOW
                or info.activity_type
                != ("finalize_narrative_style_job" if finalizer else "run_narrative_style_job")
                or info.is_local
                or type(info.attempt) is not int
                or info.attempt < 1
                or str(run_id) != info.workflow_run_id
            ):
                raise ValueError
            return data, run_id, info.attempt
        except Exception:
            raise ApplicationError("activity_identity", non_retryable=True) from None

    @activity.defn(name="run_narrative_style_job")
    async def run(self, payload: ImageJobPayload) -> ImageJobOutcome:
        data, run_id, attempt = self.context(payload)
        token = uuid4()
        async with self.factory() as session:
            row = await session.get(NarrativeStyleJob, UUID(data["job_id"]), with_for_update=True)
            if row is None or str(row.tenant_id) != data["tenant_id"]:
                raise ApplicationError("style_identity", non_retryable=True)
            if row.workflow_run_id is None:
                raise ApplicationError("registration_pending")
            if row.workflow_run_id != run_id or row.activity_attempt > attempt:
                return {"job_id": str(row.id), "status": "stale"}
            if row.status not in ACTIVE:
                return outcome(row)
            # An attempt can only be claimed once. Higher Temporal attempts supersede it.
            if row.activity_attempt == attempt:
                return {"job_id": str(row.id), "status": "stale"}
            row.status, row.activity_attempt, row.execution_token = "running", attempt, token
            row.progress = 0
            await session.commit()
        job_id = row.id

        async def progress(step: int) -> None:
            async with self.factory() as session:
                current = await session.get(NarrativeStyleJob, job_id, with_for_update=True)
                if (
                    current is None
                    or current.execution_token != token
                    or current.status != "running"
                ):
                    raise Superseded
                if current.cancel_requested:
                    raise asyncio.CancelledError
                current.progress = max(current.progress, step)
                await session.commit()

        async def watch() -> None:
            while True:
                activity.heartbeat()
                await progress(0)
                await asyncio.sleep(3)

        async def train() -> StyleTrainingResult:
            if (
                row.model_manifest_sha256 != self.trainer.model_hash
                or row.recipe_sha256 != RECIPE_SHA
            ):
                raise ValueError("model_pin_mismatch")
            images = []
            async with self.factory() as session:
                try:
                    await verify_target(session, row)
                except DomainError:
                    raise ValueError("reference_unavailable") from None
                for item in row.images:
                    source = await session.get(NarrativeAsset, UUID(item["asset_id"]))
                    if (
                        source is None
                        or source.tenant_id != row.tenant_id
                        or source.project_id != row.project_id
                        or source.sha256 != item["sha256"]
                        or source.size_bytes != item["size_bytes"]
                        or source.status != "approved"
                    ):
                        raise ValueError("reference_unavailable")
                    image = await self.store.get_verified(
                        asset_object_key(
                            tenant_id=row.tenant_id,
                            project_id=row.project_id,
                            asset_id=source.id,
                            variant="image",
                        ),
                        expected_size=source.size_bytes,
                        expected_sha256=source.sha256,
                        max_bytes=8 * 1024**2,
                    )
                    images.append((image, item["caption"]))
            return await self.trainer.train(
                StyleTrainingRequest(
                    tuple(images),
                    row.dataset_sha256,
                    row.recipe_sha256,
                    row.trigger,
                    row.steps,
                    row.seed,
                ),
                on_progress=progress,
            )

        work, monitor = asyncio.create_task(train()), asyncio.create_task(watch())
        result = None
        code = None
        cancelled = False
        try:
            done, _ = await asyncio.wait({work, monitor}, return_when=asyncio.FIRST_COMPLETED)
            if monitor in done:
                await monitor
            result = await work
            validate_adapter(
                result.weights,
                base_hash=row.model_manifest_sha256,
                dataset_hash=row.dataset_sha256,
                recipe_hash=row.recipe_sha256,
            )
            await progress(row.steps)
            key = (
                f"tenants/{row.tenant_id}/narrative/projects/{row.project_id}/style-adapters/"
                f"{row.id}/executions/{token}/adapter.safetensors"
            )
            weight_hash = sha256(result.weights).hexdigest()
            await self.store.put_private_adapter(key, result.weights, expected_sha256=weight_hash)
            async with self.factory() as session:
                current = await session.get(NarrativeStyleJob, job_id, with_for_update=True)
                if (
                    current is None
                    or current.execution_token != token
                    or current.status != "running"
                ):
                    raise Superseded
                if current.cancel_requested:
                    raise asyncio.CancelledError
                current.weights_key, current.weights_sha256 = key, weight_hash
                current.weights_size = len(result.weights)
                current.losses, current.runtime = result.losses, result.runtime
                current.status, current.finished_at = "completed", datetime.now(UTC)
                await session.commit()
            if self.tracker:
                async with self.factory() as session:
                    kind = (await details(session, row))["kind"]
                tracking = await self.tracker.record(
                    job_id=job_id,
                    base_hash=row.model_manifest_sha256,
                    dataset_hash=row.dataset_sha256,
                    recipe_hash=row.recipe_sha256,
                    weights_hash=weight_hash,
                    losses=result.losses,
                    runtime=result.runtime,
                    image_count=len(row.images),
                    kind=kind,
                )
                async with self.factory() as session:
                    current = await session.get(NarrativeStyleJob, job_id)
                    if (
                        current
                        and current.status == "completed"
                        and current.execution_token == token
                    ):
                        current.tracking_run_id = tracking
                        await session.commit()
        except Superseded:
            return {"job_id": str(job_id), "status": "stale"}
        except asyncio.CancelledError:
            cancelled = True
        except Exception as error:
            code = (
                str(error)
                if isinstance(error, ValueError)
                and str(error)
                in {
                    "gpu_busy",
                    "host_memory_busy",
                    "out_of_memory",
                    "model_pin_mismatch",
                    "reference_unavailable",
                    "invalid_adapter",
                    "caption_too_long",
                }
                else "training_failed"
            )
        finally:
            work.cancel()
            monitor.cancel()
            for task in (work, monitor):
                with suppress(asyncio.CancelledError, Exception):
                    await task
        async with self.factory() as session:
            current = await session.get(NarrativeStyleJob, job_id, with_for_update=True)
            assert current
            if current.execution_token != token:
                return {"job_id": str(job_id), "status": "stale"}
            if current.status in ACTIVE:
                if (
                    not cancelled
                    and code in {"gpu_busy", "host_memory_busy", "out_of_memory"}
                    and attempt < 3
                ):
                    await session.commit()
                    raise ApplicationError(code)
                current.status = "cancelled" if cancelled or current.cancel_requested else "failed"
                current.error_code, current.finished_at = code, datetime.now(UTC)
            await session.commit()
            return outcome(current)

    @activity.defn(name="finalize_narrative_style_job")
    async def finalize(self, payload: dict[str, Any]) -> ImageJobOutcome:
        if (
            set(payload) != {"schema_version", "tenant_id", "job_id", "cancelled"}
            or type(payload["cancelled"]) is not bool
        ):
            raise ApplicationError("activity_identity", non_retryable=True)
        data, run_id, _ = self.context(
            {k: v for k, v in payload.items() if k != "cancelled"}, finalizer=True
        )
        async with self.factory() as session:
            row = await session.get(NarrativeStyleJob, UUID(data["job_id"]), with_for_update=True)
            if (
                row is None
                or str(row.tenant_id) != data["tenant_id"]
                or row.workflow_run_id != run_id
            ):
                return {"job_id": data["job_id"], "status": "stale"}
            if row.status in ACTIVE:
                row.status = (
                    "cancelled" if payload["cancelled"] or row.cancel_requested else "failed"
                )
                row.error_code, row.finished_at, row.execution_token = (
                    "worker_interrupted",
                    datetime.now(UTC),
                    None,
                )
                await session.commit()
            return outcome(row)
