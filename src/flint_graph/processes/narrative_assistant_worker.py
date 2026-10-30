"""Explicit opt-in assistant worker: dispatch, model calls and recovery in one process.

It consumes only assistant outbox topics and runs only on its own task queue, so the
Godot build worker and ingestion are unaffected. Logs carry counts, never text.
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from temporalio.client import Client
from temporalio.worker import Worker

from flint_graph.application.services.narrative_assistant_relay import (
    AssistantDispatcher,
    recover_stale_turns,
    relay_assistant_batch,
)
from flint_graph.config import Settings, get_settings
from flint_graph.infrastructure.narrative_assistant import build_narrative_assistant
from flint_graph.infrastructure.narrative_assistant_temporal import TemporalAssistantDispatcher
from flint_graph.worker.activities.narrative_assistant import NarrativeAssistantActivities
from flint_graph.workflows.narrative_assistant import NarrativeAssistantTurnWorkflow

logger = logging.getLogger(__name__)
RECOVERY_EVERY = timedelta(seconds=60)


async def maintain(
    factory: async_sessionmaker[AsyncSession],
    *,
    dispatcher: AssistantDispatcher,
    poll_interval_seconds: float,
) -> None:
    loop = asyncio.get_running_loop()
    next_recovery = loop.time()
    while True:
        try:
            count = await relay_assistant_batch(factory, dispatcher=dispatcher)
            if count:
                logger.info("assistant dispatch completed: %d", count)
            if loop.time() >= next_recovery:
                next_recovery = loop.time() + RECOVERY_EVERY.total_seconds()
                recovered = await recover_stale_turns(factory, dispatcher=dispatcher)
                if recovered:
                    logger.warning("assistant turns recovered: %d", recovered)
        except Exception:
            logger.warning("assistant dispatch unavailable")
        await asyncio.sleep(poll_interval_seconds)


async def run_worker(settings: Settings | None = None) -> None:
    configured = settings or get_settings()
    if not configured.narrative_assistant_worker_enabled:
        raise SystemExit("The assistant worker is disabled; explicit operator opt-in is required.")
    model = build_narrative_assistant(configured)
    if model is None:
        raise SystemExit("The assistant provider is disabled; choose one explicitly.")
    # No generic tracing interceptor: workflow headers/memo stay closed, IDs-only.
    temporal = await Client.connect(
        configured.temporal_address, namespace=configured.temporal_namespace
    )
    queue = configured.narrative_assistant_task_queue
    dispatcher = TemporalAssistantDispatcher(temporal, task_queue=queue)
    engine = create_async_engine(configured.database_url, hide_parameters=True, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    activities = NarrativeAssistantActivities(
        factory=factory, model=model, context_chars=configured.narrative_assistant_context_chars
    )
    try:
        async with Worker(
            temporal,
            task_queue=queue,
            workflows=[NarrativeAssistantTurnWorkflow],
            activities=[activities.run, activities.finalize],
            max_concurrent_activities=configured.narrative_assistant_max_active_turns_per_workspace,
            max_heartbeat_throttle_interval=timedelta(seconds=5),
            graceful_shutdown_timeout=timedelta(seconds=30),
        ):
            await maintain(
                factory,
                dispatcher=dispatcher,
                poll_interval_seconds=configured.narrative_assistant_poll_interval_seconds,
            )
    finally:
        await engine.dispose()


def main() -> None:
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass
    except Exception:
        raise SystemExit("Assistant worker failed; verify operator configuration.") from None


if __name__ == "__main__":
    main()
