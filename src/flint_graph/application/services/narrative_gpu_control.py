"""Start the GPU machine when work is queued, and stop it when there is none (ADR 0070).

``decide`` is pure, so every transition can be tested without a machine. ``GpuController``
reads the world, applies the decision, and records what the machine is doing for the Studio.

Stopping only happens when the database says nothing is queued or running. A job that
arrives while the machine stops stays queued, durably, and the next look starts it again;
a job interrupted by a safety stop follows the existing retry and recovery fences.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flint_graph.application.services.narrative_gpu import (
    CONTROLLER,
    expected_kinds,
    record_gpu_state,
)
from flint_graph.config import Settings
from flint_graph.infrastructure.db.models import (
    NarrativeAssistantTurn,
    NarrativeImageJob,
    NarrativeMusicJob,
    NarrativeVoiceJob,
)
from flint_graph.infrastructure.db.narrative_assistant_models import NarrativeAssistantAction
from flint_graph.infrastructure.db.narrative_gpu_models import (
    NarrativeGpuSession,
    NarrativeGpuStatus,
)
from flint_graph.infrastructure.db.narrative_style_models import NarrativeStyleJob

logger = logging.getLogger(__name__)

_ACTIVE = ("queued", "running")
_KEEP_SESSIONS = timedelta(days=30)
_RETRY_FIRST = timedelta(seconds=30)
_RETRY_MOST = timedelta(minutes=5)


class NoCapacity(Exception):
    """The cloud has no machine of this type to give right now."""


@dataclass(frozen=True)
class InstanceView:
    # pending, running, stopping, stopped, or missing when there is no such machine.
    state: str
    launched_at: datetime | None = None


class GpuInstance(Protocol):
    async def describe(self) -> InstanceView: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


@dataclass(frozen=True)
class Policy:
    idle: timedelta = timedelta(minutes=5)
    max_session: timedelta = timedelta(hours=4)
    # How long a machine may take to boot and load before its silence counts against it.
    boot_grace: timedelta = timedelta(minutes=10)
    silent: timedelta = timedelta(minutes=5)
    daily_cap: timedelta | None = None


@dataclass(frozen=True)
class Seen:
    now: datetime
    instance: InstanceView
    work: int
    last_beat: datetime | None
    idle_since: datetime | None
    used_today: timedelta


@dataclass(frozen=True)
class Step:
    state: str
    action: str | None = None
    detail: str | None = None
    idle_since: datetime | None = None
    alarm: str | None = None


def decide(seen: Seen, policy: Policy) -> Step:
    capped = policy.daily_cap is not None and seen.used_today >= policy.daily_cap
    instance = seen.instance
    if instance.state == "pending":
        return Step("starting")
    if instance.state in ("stopping", "shutting-down"):
        return Step("stopping")
    if instance.state == "stopped":
        if not seen.work:
            return Step("stopped")
        if capped:
            return Step("unavailable", detail="daily_cap", alarm="daily_cap")
        return Step("starting", action="start")
    if instance.state != "running":
        return Step("unavailable", detail="instance_missing", alarm="instance_missing")
    session = seen.now - instance.launched_at if instance.launched_at else timedelta(0)
    if session >= policy.max_session:
        return Step("stopping", action="stop", alarm="session_too_long")
    if capped:
        return Step("unavailable", action="stop", detail="daily_cap", alarm="daily_cap")
    quiet = seen.last_beat is None or seen.now - seen.last_beat > policy.silent
    if quiet and session >= policy.boot_grace:
        return Step("stopping", action="stop", alarm="heartbeat_stale")
    if seen.work:
        return Step("ready")
    since = seen.idle_since or seen.now
    if seen.now - since >= policy.idle:
        return Step("stopping", action="stop")
    return Step("ready", idle_since=since)


async def gpu_work(session: AsyncSession, settings: Settings) -> int:
    """How much GPU work is queued or running, including presses waiting for a free slot."""
    expected = expected_kinds(settings)
    tables: list[tuple[str, type]] = [
        ("image", NarrativeImageJob),
        ("pose", NarrativeImageJob),
        ("voice", NarrativeVoiceJob),
        ("style", NarrativeStyleJob),
        ("music", NarrativeMusicJob),
        ("assistant", NarrativeAssistantTurn),
    ]
    total = 0
    counted: set[type] = set()
    for kind, table in tables:
        if kind in expected and table not in counted:
            counted.add(table)
            status = table.status  # type: ignore[attr-defined]
            found = await session.scalar(select(func.count()).where(status.in_(_ACTIVE)))
            total += int(found or 0)
    waiting = await session.scalar(
        select(func.count()).where(NarrativeAssistantAction.status == "pending")
    )
    return total + int(waiting or 0)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def _used_today(session: AsyncSession, now: datetime) -> timedelta:
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    used = timedelta(0)
    for row in await session.scalars(
        select(NarrativeGpuSession).where(NarrativeGpuSession.last_seen_at >= midnight)
    ):
        start = max(_aware(row.started_at), midnight)
        used += max(_aware(row.last_seen_at) - start, timedelta(0))
    return used


async def _note_session(session: AsyncSession, started_at: datetime, now: datetime) -> None:
    row = await session.get(NarrativeGpuSession, started_at)
    if row is None:
        session.add(NarrativeGpuSession(started_at=started_at, last_seen_at=now))
    else:
        row.last_seen_at = now
    await session.execute(
        delete(NarrativeGpuSession).where(NarrativeGpuSession.last_seen_at < now - _KEEP_SESSIONS)
    )


class GpuController:
    """One look at the world per ``tick``. Only one should run; a second is merely redundant,
    since starting or stopping a machine already doing so changes nothing."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        *,
        instance: GpuInstance,
        settings: Settings,
        policy: Policy,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.factory, self.instance, self.settings = factory, instance, settings
        self.policy, self.clock = policy, clock
        self.idle_since: datetime | None = None
        self.retry_at: datetime | None = None
        self.refusals = 0

    async def tick(self) -> Step:
        now = self.clock()
        view = await self.instance.describe()
        async with self.factory() as session:
            if view.state == "running" and view.launched_at is not None:
                await _note_session(session, view.launched_at, now)
            work = await gpu_work(session, self.settings)
            used = await _used_today(session, now)
            beat = await session.scalar(
                select(func.max(NarrativeGpuStatus.updated_at)).where(
                    NarrativeGpuStatus.name != CONTROLLER
                )
            )
            await session.commit()
        step = decide(
            Seen(now, view, work, _aware(beat) if beat else None, self.idle_since, used),
            self.policy,
        )
        self.idle_since = step.idle_since
        step = await self._act(step, now)
        if step.alarm:
            # Operators alarm on this line; it holds a reason and nothing else.
            logger.error("gpu controller alarm: %s", step.alarm)
        async with self.factory() as session:
            await record_gpu_state(session, CONTROLLER, step.state, step.detail, now=now)
            await session.commit()
        return step

    async def _act(self, step: Step, now: datetime) -> Step:
        if step.action == "stop":
            await self.instance.stop()
        elif step.action == "start":
            if self.retry_at is not None and now < self.retry_at:
                return Step("unavailable", detail="no_capacity")
            try:
                await self.instance.start()
            except NoCapacity:
                wait = min(_RETRY_FIRST * 2**self.refusals, _RETRY_MOST)
                self.refusals += 1
                self.retry_at = now + wait
                return Step("unavailable", detail="no_capacity", alarm="no_capacity")
            self.refusals, self.retry_at = 0, None
        return step
