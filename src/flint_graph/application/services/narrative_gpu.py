"""Is the GPU up, and if not, what should a person be told? (#201, ADR 0069)

GPU workers keep a row fresh while they run, so the answer comes from the machine itself
and works the same on a laptop or in the cloud. The controller that starts and stops the
machine (#197) records what it is doing here too. Nothing waits on this: it only words a
message, and queued jobs stay durable either way.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flint_graph.config import Settings
from flint_graph.infrastructure.db.narrative_gpu_models import NarrativeGpuStatus

logger = logging.getLogger(__name__)

CONTROLLER = "controller"
CONTROLLER_STATES = ("ready", "stopped", "starting", "stopping", "unavailable")
HEARTBEAT_SECONDS = 20.0
# Missing two beats is not yet gone: a beat can be late while a model loads.
WORKER_STALE = timedelta(seconds=60)
# The controller may be a scheduled job, so it writes less often than a worker.
CONTROLLER_STALE = timedelta(minutes=5)


@dataclass(frozen=True)
class GpuView:
    state: str  # ready, asleep, starting, stopping, unavailable or off
    detail: str | None
    wake_seconds: int | None
    # The kinds of work this server does that would wait right now.
    waiting: tuple[str, ...]


def expected_kinds(settings: Settings) -> tuple[str, ...]:
    """The work this server is set up to run on a GPU."""
    enabled = (
        ("image", settings.narrative_image_generation_enabled),
        ("voice", settings.narrative_voice_generation_enabled),
        ("pose", settings.narrative_pose_generation_enabled),
        ("style", settings.narrative_style_training_enabled),
        # A hosted assistant has no GPU to wait for.
        ("assistant", settings.narrative_assistant_provider == "ollama"),
    )
    return tuple(kind for kind, on in enabled if on)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def gpu_view(
    rows: Iterable[NarrativeGpuStatus],
    *,
    now: datetime,
    expected: Iterable[str],
    sleeps: bool,
    wake_seconds: int | None,
) -> GpuView:
    known = {row.name: row for row in rows}
    fresh = {
        name
        for name, row in known.items()
        if name != CONTROLLER and now - _aware(row.updated_at) <= WORKER_STALE
    }
    waiting = tuple(kind for kind in expected if kind not in fresh)
    state, detail = "ready", None
    if waiting:
        controller = known.get(CONTROLLER)
        if not sleeps:
            state = "off"  # Nothing here wakes it, so promising a wake-up would be false.
        elif fresh:
            state = "starting"  # The machine is up, and these are still loading.
        elif controller is None or now - _aware(controller.updated_at) > CONTROLLER_STALE:
            state, detail = "unavailable", "controller_down"
        elif controller.state == "stopped":
            state = "asleep"
        elif controller.state == "ready":
            state = "starting"
        else:
            state, detail = controller.state, controller.detail
    return GpuView(state, detail, wake_seconds if sleeps else None, waiting)


async def read_gpu_view(session: AsyncSession, settings: Settings) -> GpuView:
    rows = await session.scalars(select(NarrativeGpuStatus))
    return gpu_view(
        rows,
        now=datetime.now(UTC),
        expected=expected_kinds(settings),
        sleeps=settings.narrative_gpu_sleeps,
        wake_seconds=settings.narrative_gpu_wake_seconds,
    )


async def record_gpu_state(
    session: AsyncSession, name: str, state: str = "ready", detail: str | None = None
) -> None:
    """A worker saying it is up, or the controller saying what the machine is doing."""
    if state not in CONTROLLER_STATES:
        raise ValueError(f"Unknown GPU state: {state}.")
    row = await session.get(NarrativeGpuStatus, name)
    now = datetime.now(UTC)
    if row is None:
        session.add(NarrativeGpuStatus(name=name, state=state, detail=detail, updated_at=now))
    else:
        row.state, row.detail, row.updated_at = state, detail, now
    await session.flush()


async def _beat_forever(
    factory: async_sessionmaker[AsyncSession], worker: str, every: float
) -> None:
    while True:
        try:
            async with factory() as session:
                await record_gpu_state(session, worker)
                await session.commit()
        except Exception:
            # Only a message depends on this; a worker must keep working without it.
            logger.warning("gpu heartbeat unavailable: %s", worker)
        await asyncio.sleep(every)


@asynccontextmanager
async def gpu_heartbeat(
    factory: async_sessionmaker[AsyncSession], worker: str, every: float = HEARTBEAT_SECONDS
) -> AsyncIterator[None]:
    """Say this worker is up for as long as the block runs."""
    task = asyncio.create_task(_beat_forever(factory, worker, every))
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
