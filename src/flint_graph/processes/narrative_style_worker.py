"""Opt-in single-training Temporal worker with private artifact publication."""

import asyncio
import logging
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from temporalio.client import Client
from temporalio.worker import Worker

from flint_graph.application.services.narrative_gpu import gpu_heartbeat
from flint_graph.application.services.narrative_style_relay import (
    recover_style_jobs,
    relay_style_batch,
)
from flint_graph.application.services.narrative_styles import WORKFLOW, workflow_id
from flint_graph.config import get_settings
from flint_graph.infrastructure.narrative_artifact_store import S3NarrativeArtifactStore
from flint_graph.infrastructure.narrative_image_temporal import TemporalImageDispatcher
from flint_graph.infrastructure.narrative_model_tracking import ModelTracker
from flint_graph.infrastructure.narrative_posegen import verify_pose_model
from flint_graph.infrastructure.narrative_stylegen import LocalStyleTrainer
from flint_graph.infrastructure.object_store import create_s3_client
from flint_graph.worker.activities.narrative_style import NarrativeStyleActivities
from flint_graph.workflows.narrative_style import NarrativeStyleJobWorkflow

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    settings = get_settings()
    if not settings.narrative_style_worker_enabled:
        raise SystemExit("Style worker is disabled.")
    runtime = Path(settings.narrative_style_runtime_dir or "")
    model = Path(settings.narrative_pose_model_dir or "")
    pin = settings.narrative_pose_model_manifest_sha256
    pose_runtime = Path(settings.narrative_pose_runtime_dir or "")
    python = runtime / (
        ".venv/Scripts/python.exe" if sys.platform == "win32" else ".venv/bin/python"
    )
    script = runtime / "train.py"
    if not (
        runtime.is_absolute()
        and model.is_absolute()
        and pose_runtime.is_absolute()
        and pin
        and python.is_file()
        and script.is_file()
    ):
        raise SystemExit("Install and configure the style runtime and pinned pose model.")
    if settings.narrative_style_task_queue in {
        settings.narrative_pose_task_queue,
        settings.narrative_image_task_queue,
        settings.temporal_task_queue,
    }:
        raise SystemExit("Use a dedicated style queue.")
    await asyncio.to_thread(verify_pose_model, model, pin, pose_runtime)
    trainer = LocalStyleTrainer(
        python=python,
        script=script,
        model_dir=model,
        model_hash=pin,
        deadline=settings.narrative_style_deadline_seconds,
    )
    temporal = await Client.connect(
        settings.temporal_address, namespace=settings.temporal_namespace
    )
    dispatcher = TemporalImageDispatcher(
        temporal,
        task_queue=settings.narrative_style_task_queue,
        workflow=WORKFLOW,
        workflow_id=workflow_id,
    )
    engine = create_async_engine(settings.database_url, hide_parameters=True, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    client = create_s3_client(settings, max_attempts=3)
    store = S3NarrativeArtifactStore(client, bucket=settings.object_store_bucket)
    tracker = (
        ModelTracker(settings.narrative_model_tracking_url)
        if settings.narrative_model_tracking_url
        else None
    )
    activities = NarrativeStyleActivities(
        factory=factory, trainer=trainer, store=store, tracker=tracker
    )
    try:
        async with (
            Worker(
                temporal,
                task_queue=settings.narrative_style_task_queue,
                workflows=[NarrativeStyleJobWorkflow],
                activities=[activities.run, activities.finalize],
                max_concurrent_activities=1,
                max_heartbeat_throttle_interval=timedelta(seconds=5),
                graceful_shutdown_timeout=timedelta(seconds=30),
            ),
            gpu_heartbeat(factory, "style"),
        ):
            recovery = 0.0
            while True:
                try:
                    await relay_style_batch(factory, dispatcher=dispatcher)
                    if asyncio.get_running_loop().time() > recovery:
                        recovery = asyncio.get_running_loop().time() + 60
                        await recover_style_jobs(factory, dispatcher=dispatcher)
                except Exception:
                    logger.warning("style dispatch unavailable")
                await asyncio.sleep(1)
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
        raise SystemExit("Style worker failed; verify operator configuration.") from None


if __name__ == "__main__":
    main()
