"""The always-on dispatcher for GPU work (ADR 0070). It needs no GPU and runs no model.

It needs the API's database, Temporal, object-store and generation settings, since starting an
action admits a normal job. Logs carry counts, never text.
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from temporalio.client import Client

from flint_graph.application.narrative_image_workflow import (
    MUSIC_WORKFLOW,
    VOICE_WORKFLOW,
    music_job_workflow_id,
    voice_job_workflow_id,
)
from flint_graph.application.services.narrative_gpu_dispatch import (
    GpuDispatchers,
    dispatch_gpu_work,
)
from flint_graph.application.services.narrative_styles import WORKFLOW, workflow_id
from flint_graph.config import Settings, get_settings
from flint_graph.infrastructure.narrative_artifact_store import S3NarrativeArtifactStore
from flint_graph.infrastructure.narrative_assistant_temporal import TemporalAssistantDispatcher
from flint_graph.infrastructure.narrative_image_temporal import TemporalImageDispatcher
from flint_graph.infrastructure.object_store import create_s3_client
from flint_graph.prompts.runtime import run_prompt_process

logger = logging.getLogger(__name__)
RECOVERY_EVERY = timedelta(seconds=60)


def build_dispatchers(temporal: Client, settings: Settings) -> GpuDispatchers:
    """A dispatcher for each kind of GPU work this server is set up to run."""
    return GpuDispatchers(
        image=(
            TemporalImageDispatcher(temporal, task_queue=settings.narrative_image_task_queue)
            if settings.narrative_image_generation_enabled
            else None
        ),
        pose=(
            TemporalImageDispatcher(temporal, task_queue=settings.narrative_pose_task_queue)
            if settings.narrative_pose_generation_enabled
            else None
        ),
        voice=(
            TemporalImageDispatcher(
                temporal,
                task_queue=settings.narrative_voice_task_queue,
                workflow=VOICE_WORKFLOW,
                workflow_id=voice_job_workflow_id,
            )
            if settings.narrative_voice_generation_enabled
            else None
        ),
        style=(
            TemporalImageDispatcher(
                temporal,
                task_queue=settings.narrative_style_task_queue,
                workflow=WORKFLOW,
                workflow_id=workflow_id,
            )
            if settings.narrative_style_training_enabled
            else None
        ),
        music=(
            TemporalImageDispatcher(
                temporal,
                task_queue=settings.narrative_music_task_queue,
                workflow=MUSIC_WORKFLOW,
                workflow_id=music_job_workflow_id,
            )
            if settings.narrative_music_generation_enabled
            else None
        ),
        assistant=(
            TemporalAssistantDispatcher(
                temporal, task_queue=settings.narrative_assistant_task_queue
            )
            if settings.narrative_assistant_provider not in (None, "disabled")
            else None
        ),
    )


async def run_dispatcher(settings: Settings | None = None) -> None:
    configured = settings or get_settings()
    if not configured.narrative_gpu_dispatch_enabled:
        raise SystemExit("The GPU dispatcher is disabled; explicit operator opt-in is required.")
    temporal = await Client.connect(
        configured.temporal_address, namespace=configured.temporal_namespace
    )
    dispatchers = build_dispatchers(temporal, configured)
    engine = create_async_engine(configured.database_url, hide_parameters=True, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    client = create_s3_client(configured, max_attempts=3)
    store = S3NarrativeArtifactStore(client, bucket=configured.object_store_bucket)
    loop = asyncio.get_running_loop()
    next_recovery = loop.time()
    try:
        while True:
            recover = loop.time() >= next_recovery
            if recover:
                next_recovery = loop.time() + RECOVERY_EVERY.total_seconds()
            done = await dispatch_gpu_work(
                factory, dispatchers=dispatchers, settings=configured, store=store, recover=recover
            )
            if any(done.values()):
                logger.info("gpu dispatch: %s", {k: v for k, v in done.items() if v})
            await asyncio.sleep(configured.narrative_gpu_dispatch_poll_interval_seconds)
    finally:
        client.close()
        await engine.dispose()


def main() -> None:
    try:
        asyncio.run(run_prompt_process(run_dispatcher))
    except KeyboardInterrupt:
        pass
    except Exception:
        raise SystemExit("GPU dispatcher failed; verify operator configuration.") from None


if __name__ == "__main__":
    main()
