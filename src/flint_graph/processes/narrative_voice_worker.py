"""Explicit opt-in voice worker: dispatch, local CPU speech and recovery (ADR 0043).

It consumes only voice outbox topics and runs on its own task queue, one job at a
time. The Kokoro directory is verified against its pinned manifest before any job
runs. Logs carry counts, never the spoken text.
"""

import asyncio
import logging
from datetime import timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from temporalio.client import Client
from temporalio.worker import Worker

from flint_graph.application.narrative_image_workflow import VOICE_WORKFLOW, voice_job_workflow_id
from flint_graph.application.services.narrative_image_relay import ImageDispatcher
from flint_graph.application.services.narrative_voice_relay import (
    recover_stale_voice_jobs,
    relay_voice_batch,
)
from flint_graph.config import Settings, get_settings
from flint_graph.infrastructure.narrative_artifact_store import S3NarrativeArtifactStore
from flint_graph.infrastructure.narrative_image_temporal import TemporalImageDispatcher
from flint_graph.infrastructure.narrative_voicegen import (
    LocalVoiceGenerator,
    verify_voice_model,
    voice_runtime_paths,
)
from flint_graph.infrastructure.object_store import create_s3_client
from flint_graph.worker.activities.narrative_voice import NarrativeVoiceActivities
from flint_graph.workflows.narrative_voice import NarrativeVoiceJobWorkflow

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
            count = await relay_voice_batch(factory, dispatcher=dispatcher)
            if count:
                logger.info("voice dispatch completed: %d", count)
            if loop.time() >= next_recovery:
                next_recovery = loop.time() + RECOVERY_EVERY.total_seconds()
                recovered = await recover_stale_voice_jobs(factory, dispatcher=dispatcher)
                if recovered:
                    logger.warning("voice jobs recovered: %d", recovered)
        except Exception:
            logger.warning("voice dispatch unavailable")
        await asyncio.sleep(poll_interval_seconds)


def build_generator(configured: Settings) -> LocalVoiceGenerator:
    assert configured.narrative_voice_runtime_dir and configured.narrative_voice_model_dir
    assert configured.narrative_voice_model_manifest_sha256
    python, script = voice_runtime_paths(Path(configured.narrative_voice_runtime_dir))
    if not python.is_file() or not script.is_file():
        raise SystemExit("The voice runtime is not installed; run uv sync in runtimes/voicegen.")
    model_dir = Path(configured.narrative_voice_model_dir)
    try:
        model, _ = verify_voice_model(model_dir, configured.narrative_voice_model_manifest_sha256)
    except (OSError, ValueError):
        raise SystemExit("The voice model does not match its pinned manifest.") from None
    return LocalVoiceGenerator(
        python=python,
        script=script,
        model_dir=model_dir.resolve(),
        model=model,
        deadline_seconds=configured.narrative_voice_job_deadline_seconds,
    )


async def run_worker(settings: Settings | None = None) -> None:
    configured = settings or get_settings()
    if not configured.narrative_voice_worker_enabled:
        raise SystemExit("The voice worker is disabled; explicit operator opt-in is required.")
    generator = await asyncio.to_thread(build_generator, configured)
    logger.info("voice model verified")
    # No generic tracing interceptor: workflow headers/memo stay closed, IDs-only.
    temporal = await Client.connect(
        configured.temporal_address, namespace=configured.temporal_namespace
    )
    queue = configured.narrative_voice_task_queue
    dispatcher = TemporalImageDispatcher(
        temporal, task_queue=queue, workflow=VOICE_WORKFLOW, workflow_id=voice_job_workflow_id
    )
    engine = create_async_engine(configured.database_url, hide_parameters=True, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    client = create_s3_client(configured, max_attempts=3)
    store = S3NarrativeArtifactStore(client, bucket=configured.object_store_bucket)
    activities = NarrativeVoiceActivities(factory=factory, generator=generator, store=store)
    try:
        async with Worker(
            temporal,
            task_queue=queue,
            workflows=[NarrativeVoiceJobWorkflow],
            activities=[activities.run, activities.finalize],
            max_concurrent_activities=1,
            max_heartbeat_throttle_interval=timedelta(seconds=5),
            graceful_shutdown_timeout=timedelta(seconds=30),
        ):
            await maintain(
                factory,
                dispatcher=dispatcher,
                poll_interval_seconds=configured.narrative_voice_poll_interval_seconds,
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
        raise SystemExit("Voice worker failed; verify operator configuration.") from None


if __name__ == "__main__":
    main()
