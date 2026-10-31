"""Explicit opt-in image worker: dispatch, local GPU generation and recovery (ADR 0039).

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

from flint_graph.application.services.narrative_image_relay import (
    ImageDispatcher,
    recover_stale_image_jobs,
    relay_image_batch,
)
from flint_graph.config import Settings, get_settings
from flint_graph.infrastructure.narrative_artifact_store import S3NarrativeArtifactStore
from flint_graph.infrastructure.narrative_image_temporal import TemporalImageDispatcher
from flint_graph.infrastructure.narrative_imagegen import (
    LocalImageGenerator,
    OllamaGpuReleaser,
    runtime_paths,
    verify_cutout_model,
    verify_model,
)
from flint_graph.infrastructure.object_store import create_s3_client
from flint_graph.worker.activities.narrative_image import NarrativeImageActivities
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
            count = await relay_image_batch(factory, dispatcher=dispatcher)
            if count:
                logger.info("image dispatch completed: %d", count)
            if loop.time() >= next_recovery:
                next_recovery = loop.time() + RECOVERY_EVERY.total_seconds()
                recovered = await recover_stale_image_jobs(factory, dispatcher=dispatcher)
                if recovered:
                    logger.warning("image jobs recovered: %d", recovered)
        except Exception:
            logger.warning("image dispatch unavailable")
        await asyncio.sleep(poll_interval_seconds)


def build_generator(configured: Settings) -> LocalImageGenerator:
    assert configured.narrative_image_runtime_dir and configured.narrative_image_model_dir
    assert configured.narrative_image_model_manifest_sha256
    python, script = runtime_paths(Path(configured.narrative_image_runtime_dir))
    if not python.is_file() or not script.is_file():
        raise SystemExit("The image runtime is not installed; run uv sync in runtimes/imagegen.")
    model_dir = Path(configured.narrative_image_model_dir)
    try:
        model = verify_model(model_dir, configured.narrative_image_model_manifest_sha256)
    except (OSError, ValueError):
        raise SystemExit("The image model does not match its pinned manifest.") from None
    cutout = None
    if configured.narrative_image_cutout_model_dir:
        assert configured.narrative_image_cutout_manifest_sha256
        try:
            cutout = verify_cutout_model(
                Path(configured.narrative_image_cutout_model_dir),
                configured.narrative_image_cutout_manifest_sha256,
            )
        except (OSError, ValueError):
            raise SystemExit("The cutout model does not match its pinned manifest.") from None
    return LocalImageGenerator(
        python=python,
        script=script,
        model_dir=model_dir.resolve(),
        model=model,
        deadline_seconds=configured.narrative_image_job_deadline_seconds,
        cutout=cutout,
    )


async def run_worker(settings: Settings | None = None) -> None:
    configured = settings or get_settings()
    if not configured.narrative_image_worker_enabled:
        raise SystemExit("The image worker is disabled; explicit operator opt-in is required.")
    generator = await asyncio.to_thread(build_generator, configured)
    logger.info(
        "image model verified; cutout %s", "ready" if generator.cutout else "not configured"
    )
    releaser = (
        OllamaGpuReleaser(
            configured.ollama_base_url, configured.narrative_image_release_ollama_model
        )
        if configured.narrative_image_release_ollama_model
        else None
    )
    # No generic tracing interceptor: workflow headers/memo stay closed, IDs-only.
    temporal = await Client.connect(
        configured.temporal_address, namespace=configured.temporal_namespace
    )
    queue = configured.narrative_image_task_queue
    dispatcher = TemporalImageDispatcher(temporal, task_queue=queue)
    engine = create_async_engine(configured.database_url, hide_parameters=True, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    client = create_s3_client(configured, max_attempts=3)
    store = S3NarrativeArtifactStore(client, bucket=configured.object_store_bucket)
    activities = NarrativeImageActivities(
        factory=factory, generator=generator, store=store, releaser=releaser
    )
    try:
        async with Worker(
            temporal,
            task_queue=queue,
            workflows=[NarrativeImageJobWorkflow],
            activities=[activities.run, activities.finalize],
            max_concurrent_activities=1,
            max_heartbeat_throttle_interval=timedelta(seconds=5),
            graceful_shutdown_timeout=timedelta(seconds=30),
        ):
            await maintain(
                factory,
                dispatcher=dispatcher,
                poll_interval_seconds=configured.narrative_image_poll_interval_seconds,
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
        raise SystemExit("Image worker failed; verify operator configuration.") from None


if __name__ == "__main__":
    main()
