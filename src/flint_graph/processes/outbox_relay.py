import asyncio

import structlog

from flint_graph.application.services.outbox_relay import relay_outbox_batch
from flint_graph.config import get_settings
from flint_graph.infrastructure.db.session import SessionFactory
from flint_graph.infrastructure.temporal import TemporalIngestionWorkflowStarter, connect_temporal
from flint_graph.logging import configure_logging

logger = structlog.get_logger(__name__)


async def relay_once() -> int:
    settings = get_settings()
    client = await connect_temporal(settings)
    starter = TemporalIngestionWorkflowStarter(
        client,
        task_queue=settings.temporal_task_queue,
        workflow_name=settings.temporal_workflow_name,
    )
    async with SessionFactory() as session:
        try:
            published = await relay_outbox_batch(
                session,
                workflow_starter=starter,
                relay_id=settings.outbox_relay_id,
                batch_size=settings.outbox_relay_batch_size,
                retry_delay_seconds=settings.outbox_relay_retry_delay_seconds,
            )
            await session.commit()
            return published
        except Exception:
            await session.commit()
            raise


async def run_forever() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    while True:
        try:
            published = await relay_once()
            if published:
                logger.info("outbox_relay.published", count=published)
        except Exception as exc:
            logger.warning("outbox_relay.failed", error=str(exc))
        await asyncio.sleep(settings.outbox_relay_poll_interval_seconds)


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
