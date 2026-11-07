"""Explicit opt-in pose worker: dispatch, local GPU generation and recovery (ADR 0048).

It consumes only image outbox topics and runs on its own task queue, one job at a
time because one GPU serves one generation. The model directory is verified
against its pinned manifest before any job runs. Logs carry counts, never prompts.
"""

import asyncio
import logging
from datetime import timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from temporalio.client import Client
from temporalio.worker import Worker

from flint_graph.application.services.narrative_gpu import gpu_heartbeat, stay_up
from flint_graph.application.services.narrative_image_relay import (
    ImageDispatcher,
    recover_stale_image_jobs,
    relay_image_batch,
)
from flint_graph.config import Settings, get_settings
from flint_graph.infrastructure.narrative_artifact_store import S3NarrativeArtifactStore
from flint_graph.infrastructure.narrative_image_temporal import TemporalImageDispatcher
from flint_graph.infrastructure.narrative_imagegen import runtime_paths, verify_cutout_model
from flint_graph.infrastructure.narrative_posegen import (
    LocalPoseGenerator,
    verify_control_model,
    verify_pose_model,
)
from flint_graph.infrastructure.object_store import create_s3_client
from flint_graph.worker.activities.narrative_pose import NarrativePoseActivities
from flint_graph.workflows.narrative_image import NarrativeImageJobWorkflow

logger = logging.getLogger(__name__)
RECOVERY_EVERY = timedelta(seconds=60)


async def maintain(
    factory: async_sessionmaker[AsyncSession],
    *,
    dispatcher: ImageDispatcher,
    poll_interval_seconds: float,
) -> None:
    loop = asyncio.get_running_loop()
    next_recovery = loop.time()
    while True:
        try:
            count = await relay_image_batch(factory, dispatcher=dispatcher, poses=True)
            if count:
                logger.info("pose dispatch completed: %d", count)
            if loop.time() >= next_recovery:
                next_recovery = loop.time() + RECOVERY_EVERY.total_seconds()
                recovered = await recover_stale_image_jobs(
                    factory, dispatcher=dispatcher, poses=True
                )
                if recovered:
                    logger.warning("pose jobs recovered: %d", recovered)
        except Exception:
            logger.warning("pose dispatch unavailable")
        await asyncio.sleep(poll_interval_seconds)


def build_generator(configured: Settings) -> LocalPoseGenerator:
    assert configured.narrative_pose_runtime_dir and configured.narrative_pose_model_dir
    assert configured.narrative_pose_model_manifest_sha256
    runtime = Path(configured.narrative_pose_runtime_dir)
    python, script = runtime_paths(runtime)
    if not python.is_file() or not script.is_file():
        raise SystemExit("The pose runtime is not installed; run uv sync in runtimes/posegen.")
    model_dir = Path(configured.narrative_pose_model_dir)
    try:
        model = verify_pose_model(
            model_dir, configured.narrative_pose_model_manifest_sha256, runtime
        )
        cutout = (
            verify_cutout_model(
                Path(configured.narrative_image_cutout_model_dir),
                configured.narrative_image_cutout_manifest_sha256,
            )
            if configured.narrative_image_cutout_model_dir
            and configured.narrative_image_cutout_manifest_sha256
            else None
        )
    except (OSError, ValueError):
        raise SystemExit("The pose or cutout model does not match its pinned manifest.") from None
    if configured.narrative_pose_guides_enabled and not (
        configured.narrative_pose_control_model_dir
        and configured.narrative_pose_control_manifest_sha256
    ):
        raise SystemExit("Pose body guidance requires the pinned control model.")
    try:
        control_model = (
            verify_control_model(
                Path(configured.narrative_pose_control_model_dir),
                configured.narrative_pose_control_manifest_sha256,
            )
            if configured.narrative_pose_control_model_dir
            and configured.narrative_pose_control_manifest_sha256
            else None
        )
    except (OSError, ValueError):
        raise SystemExit("The pose control adapter does not match its pinned model.") from None
    return LocalPoseGenerator(
        python=python,
        script=script,
        model_dir=model_dir.resolve(),
        model=model,
        model_manifest_sha256=configured.narrative_pose_model_manifest_sha256,
        cutout_manifest_sha256=configured.narrative_image_cutout_manifest_sha256,
        cutout=cutout,
        control_model=control_model,
        deadline_seconds=configured.narrative_pose_job_deadline_seconds,
    )


async def run_worker(settings: Settings | None = None) -> None:
    configured = settings or get_settings()
    if not configured.narrative_pose_worker_enabled:
        raise SystemExit("The pose worker is disabled; explicit operator opt-in is required.")
    generator = await asyncio.to_thread(build_generator, configured)
    logger.info("pose model verified; cutout %s", "ready" if generator.cutout else "not configured")
    # No generic tracing interceptor: workflow headers/memo stay closed, IDs-only.
    temporal = await Client.connect(
        configured.temporal_address, namespace=configured.temporal_namespace
    )
    queue = configured.narrative_pose_task_queue
    dispatcher = TemporalImageDispatcher(temporal, task_queue=queue)
    engine = create_async_engine(configured.database_url, hide_parameters=True, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    client = create_s3_client(configured, max_attempts=3)
    store = S3NarrativeArtifactStore(client, bucket=configured.object_store_bucket)
    activities = NarrativePoseActivities(factory=factory, generator=generator, store=store)
    try:
        async with (
            Worker(
                temporal,
                task_queue=queue,
                workflows=[NarrativeImageJobWorkflow],
                activities=[activities.run, activities.finalize],
                max_concurrent_activities=1,
                max_heartbeat_throttle_interval=timedelta(seconds=5),
                graceful_shutdown_timeout=timedelta(seconds=30),
            ),
            gpu_heartbeat(factory, "pose"),
        ):
            if configured.narrative_gpu_execute_only:
                await stay_up()
            await maintain(
                factory,
                dispatcher=dispatcher,
                poll_interval_seconds=configured.narrative_pose_poll_interval_seconds,
            )
    finally:
        client.close()
        await engine.dispose()


def main() -> None:
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass
    except SystemExit:
        raise
    except Exception:
        raise SystemExit("Pose worker failed; verify operator configuration.") from None


if __name__ == "__main__":
    main()
