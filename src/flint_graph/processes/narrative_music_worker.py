"""Opt-in local music worker (ADR 0067): one track at a time on the shared GPU."""

import asyncio
import logging
import tempfile
from datetime import timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from temporalio.client import Client
from temporalio.worker import Worker

from flint_graph.application.narrative_image_workflow import (
    MUSIC_WORKFLOW,
    music_job_workflow_id,
)
from flint_graph.application.services.narrative_gpu import gpu_heartbeat
from flint_graph.application.services.narrative_image_relay import ImageDispatcher
from flint_graph.application.services.narrative_music_relay import (
    recover_stale_music_jobs,
    relay_music_batch,
)
from flint_graph.config import Settings, get_settings
from flint_graph.infrastructure.narrative_artifact_store import S3NarrativeArtifactStore
from flint_graph.infrastructure.narrative_image_temporal import TemporalImageDispatcher
from flint_graph.infrastructure.narrative_imagegen import OllamaGpuReleaser, runtime_paths
from flint_graph.infrastructure.narrative_musicgen import LocalMusicGenerator, verify_music_model
from flint_graph.infrastructure.object_store import create_s3_client
from flint_graph.worker.activities.narrative_music import NarrativeMusicActivities
from flint_graph.workflows.narrative_music import NarrativeMusicJobWorkflow

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
            count = await relay_music_batch(factory, dispatcher=dispatcher)
            if count:
                logger.info("music dispatch completed: %d", count)
            if loop.time() >= next_recovery:
                next_recovery = loop.time() + RECOVERY_EVERY.total_seconds()
                recovered = await recover_stale_music_jobs(factory, dispatcher=dispatcher)
                if recovered:
                    logger.warning("music jobs recovered: %d", recovered)
        except Exception:
            logger.warning("music dispatch unavailable")
        await asyncio.sleep(poll_interval_seconds)


def build_generator(configured: Settings) -> LocalMusicGenerator:
    assert configured.narrative_music_runtime_dir and configured.narrative_music_model_dir
    assert configured.narrative_music_model_manifest_sha256
    python, script = runtime_paths(Path(configured.narrative_music_runtime_dir))
    if not python.is_file() or not script.is_file():
        raise SystemExit("The music runtime is not installed; run uv sync in runtimes/musicgen.")
    model_dir = Path(configured.narrative_music_model_dir)
    try:
        model = verify_music_model(model_dir, configured.narrative_music_model_manifest_sha256)
    except (OSError, ValueError):
        raise SystemExit("The music model does not match its pinned manifest.") from None
    cache = Path(tempfile.gettempdir()) / "flint-graph-musicgen-cuda-cache"
    cache.mkdir(parents=True, exist_ok=True)
    return LocalMusicGenerator(
        python=python,
        script=script,
        model_dir=model_dir.resolve(),
        model=model,
        deadline_seconds=configured.narrative_music_job_deadline_seconds,
        cuda_cache=cache.resolve(),
    )


async def run_worker(settings: Settings | None = None) -> None:
    configured = settings or get_settings()
    if not configured.narrative_music_worker_enabled:
        raise SystemExit("The music worker is disabled; explicit operator opt-in is required.")
    generator = await asyncio.to_thread(build_generator, configured)
    logger.info("music model verified")
    releaser = (
        OllamaGpuReleaser(
            configured.ollama_base_url, configured.narrative_music_release_ollama_model
        )
        if configured.narrative_music_release_ollama_model
        else None
    )
    # No generic tracing interceptor: workflow headers/memo stay closed, IDs-only.
    temporal = await Client.connect(
        configured.temporal_address, namespace=configured.temporal_namespace
    )
    queue = configured.narrative_music_task_queue
    dispatcher = TemporalImageDispatcher(
        temporal, task_queue=queue, workflow=MUSIC_WORKFLOW, workflow_id=music_job_workflow_id
    )
    engine = create_async_engine(configured.database_url, hide_parameters=True, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    client = create_s3_client(configured, max_attempts=3)
    store = S3NarrativeArtifactStore(client, bucket=configured.object_store_bucket)
    activities = NarrativeMusicActivities(
        factory=factory, generator=generator, store=store, releaser=releaser
    )
    try:
        async with Worker(
            temporal,
            task_queue=queue,
            workflows=[NarrativeMusicJobWorkflow],
            activities=[activities.run, activities.finalize],
            max_concurrent_activities=1,
            max_heartbeat_throttle_interval=timedelta(seconds=5),
            graceful_shutdown_timeout=timedelta(seconds=30),
        ), gpu_heartbeat(factory, "music"):
            await maintain(
                factory,
                dispatcher=dispatcher,
                poll_interval_seconds=configured.narrative_music_poll_interval_seconds,
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
        raise SystemExit("Music worker failed; verify operator configuration.") from None


if __name__ == "__main__":
    main()
