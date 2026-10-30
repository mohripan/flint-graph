"""Separate explicitly enabled narrative outbox process; no ingestion topics."""

import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from temporalio.client import Client

from flint_graph.application.services.narrative_release_relay import relay_narrative_batch
from flint_graph.config import Settings, get_settings
from flint_graph.infrastructure.narrative_temporal import TemporalNarrativeDispatcher

logger = logging.getLogger(__name__)


async def run_forever(settings: Settings | None = None) -> None:
    configured = settings or get_settings()
    if not configured.narrative_relay_enabled:
        raise SystemExit("The narrative relay is disabled; explicit operator opt-in is required.")
    temporal = await Client.connect(
        configured.temporal_address, namespace=configured.temporal_namespace
    )
    dispatcher = TemporalNarrativeDispatcher(temporal, task_queue=configured.narrative_task_queue)
    engine = create_async_engine(configured.database_url, hide_parameters=True, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        while True:
            try:
                count = await relay_narrative_batch(
                    factory,
                    dispatcher=dispatcher,
                    batch_size=configured.narrative_relay_batch_size,
                )
                if count:
                    logger.info("narrative dispatch completed: %d", count)
            except Exception:
                logger.warning("narrative dispatch unavailable")
            await asyncio.sleep(configured.narrative_relay_poll_interval_seconds)
    finally:
        await engine.dispose()


def main() -> None:
    try:
        asyncio.run(run_forever())
    except KeyboardInterrupt:
        pass
    except Exception:
        raise SystemExit("Narrative relay failed; verify operator configuration.") from None


if __name__ == "__main__":
    main()
