"""Starts and stops the GPU machine (ADR 0070). It runs on the always-on tier, needs no GPU,
and is the only process with permission to touch the machine. Logs carry reasons, never text.
"""

import asyncio
import logging
from datetime import timedelta

import boto3  # type: ignore[import-untyped]
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flint_graph.application.services.narrative_gpu_control import GpuController, Policy
from flint_graph.config import Settings, get_settings
from flint_graph.infrastructure.narrative_gpu_ec2 import Ec2GpuInstance

logger = logging.getLogger(__name__)


def policy_from(settings: Settings) -> Policy:
    cap = settings.narrative_gpu_daily_cap_hours
    return Policy(
        idle=timedelta(seconds=settings.narrative_gpu_idle_seconds),
        max_session=timedelta(seconds=settings.narrative_gpu_max_session_seconds),
        boot_grace=timedelta(seconds=settings.narrative_gpu_boot_grace_seconds),
        silent=timedelta(seconds=settings.narrative_gpu_silent_seconds),
        daily_cap=timedelta(hours=cap) if cap is not None else None,
    )


async def run_controller(settings: Settings | None = None) -> None:
    configured = settings or get_settings()
    if not configured.narrative_gpu_controller_enabled:
        raise SystemExit("The GPU controller is disabled; explicit operator opt-in is required.")
    if not configured.narrative_gpu_region or not configured.narrative_gpu_instance_tag:
        raise SystemExit("Set the GPU region and instance tag to run the controller.")
    key, _, value = configured.narrative_gpu_instance_tag.partition("=")
    instance = Ec2GpuInstance(
        boto3.client("ec2", region_name=configured.narrative_gpu_region),
        tag_key=key,
        tag_value=value,
        instance_type=configured.narrative_gpu_instance_type,
        fallback_type=configured.narrative_gpu_fallback_instance_type,
    )
    engine = create_async_engine(configured.database_url, hide_parameters=True, pool_pre_ping=True)
    controller = GpuController(
        async_sessionmaker(engine, expire_on_commit=False),
        instance=instance,
        settings=configured,
        policy=policy_from(configured),
    )
    try:
        while True:
            try:
                step = await controller.tick()
                logger.info("gpu controller: %s %s", step.state, step.action or "")
            except Exception:
                # Left unrecorded on purpose: a silent controller reads as one that cannot act.
                logger.warning("gpu controller could not look at the machine")
            await asyncio.sleep(configured.narrative_gpu_controller_poll_seconds)
    finally:
        await engine.dispose()


def main() -> None:
    try:
        asyncio.run(run_controller())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
