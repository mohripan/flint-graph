"""Explicit opt-in narrative worker; trusted Docker access belongs only on this host."""

import asyncio
from datetime import timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from temporalio.client import Client
from temporalio.worker import Worker

from flint_graph.application.services.narrative_release_recovery import run_narrative_maintenance
from flint_graph.config import Settings, get_settings
from flint_graph.infrastructure.narrative_artifact_store import S3NarrativeArtifactStore
from flint_graph.infrastructure.narrative_builder import DockerNarrativeBuilder
from flint_graph.infrastructure.narrative_temporal import TemporalNarrativeDispatcher
from flint_graph.infrastructure.object_store import create_s3_client
from flint_graph.worker.activities.narrative_release import NarrativeReleaseActivities
from flint_graph.workflows.narrative_release import NarrativeReleaseWorkflow


async def run_worker(settings: Settings | None = None) -> None:
    configured = settings or get_settings()
    if not configured.narrative_worker_enabled:
        raise SystemExit("The narrative worker is disabled; explicit operator opt-in is required.")
    assert configured.narrative_build_work_root is not None
    assert configured.narrative_release_builder_image_digest is not None
    assert configured.narrative_release_toolchain_sha256 is not None
    builder = await asyncio.to_thread(
        DockerNarrativeBuilder,
        image=configured.narrative_release_builder_image_digest,
        toolchain_sha256=configured.narrative_release_toolchain_sha256,
        work_root=Path(configured.narrative_build_work_root),
    )
    # Deliberately no generic tracing interceptor: workflow headers/memo are closed
    # IDs-only surfaces and global propagation may contain arbitrary baggage.
    temporal = await Client.connect(
        configured.temporal_address, namespace=configured.temporal_namespace
    )
    dispatcher = TemporalNarrativeDispatcher(temporal, task_queue=configured.narrative_task_queue)
    sdk_store = create_s3_client(configured, max_attempts=3)
    store = S3NarrativeArtifactStore(sdk_store, bucket=configured.object_store_bucket)
    engine = create_async_engine(configured.database_url, hide_parameters=True, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    activities = NarrativeReleaseActivities(
        factory=factory,
        builder=builder,
        store=store,
        namespace=configured.temporal_namespace,
        task_queue=configured.narrative_task_queue,
    )
    try:
        async with Worker(
            temporal,
            task_queue=configured.narrative_task_queue,
            workflows=[NarrativeReleaseWorkflow],
            activities=[activities.build, activities.finalize],
            max_concurrent_activities=1,
            max_heartbeat_throttle_interval=timedelta(seconds=1),
            graceful_shutdown_timeout=timedelta(seconds=30),
        ):
            await run_narrative_maintenance(
                factory,
                dispatcher=dispatcher,
                builder=builder,
                interval_seconds=configured.narrative_recovery_interval_seconds,
            )
    finally:
        await asyncio.to_thread(sdk_store.close)
        await engine.dispose()


def main() -> None:
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass
    except Exception:
        raise SystemExit("Narrative worker failed; verify operator configuration.") from None


if __name__ == "__main__":
    main()
