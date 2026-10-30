"""Bounded exact closed-run recovery; running/unknown/manual work is never adopted."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flint_graph.application.narrative_workflow import ReleasePayload
from flint_graph.application.services.narrative_release_execution import (
    finalize_release_workflow,
    workflow_cleanup_plan,
)
from flint_graph.infrastructure.db.models import NarrativeReleaseJob


class ClosedRunInspector(Protocol):
    async def closed(self, payload: ReleasePayload, *, run_id: UUID) -> bool: ...


class ExecutionCleaner(Protocol):
    async def cleanup_execution(self, execution_id: UUID) -> None: ...


class MaintenanceCleaner(ExecutionCleaner, Protocol):
    async def sweep_expired(self) -> int: ...


@dataclass(frozen=True)
class RecoveryBatch:
    inspected: int
    recovered: int
    next_id: UUID | None


async def recover_narrative_jobs(
    factory: async_sessionmaker[AsyncSession],
    *,
    dispatcher: ClosedRunInspector,
    builder: ExecutionCleaner,
    after_id: UUID | None = None,
    limit: int = 50,
    pass_budget_seconds: float = 15,
) -> RecoveryBatch:
    """Cursor advances past live/unavailable runs so they cannot starve later work.

    Caller retains next_id between periodic polls, resetting after each full pass.
    The adapter verifies the exact original run/type/input before closed=True.
    Closedness is monotonic for that exact run; resets/new runs cannot take over.
    No engine/network cleanup runs while a release/job transaction is locked.
    """
    if not 1 <= limit <= 100 or not 0 < pass_budget_seconds <= 60:
        raise ValueError("Invalid narrative recovery limit")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + pass_budget_seconds
    statement = select(NarrativeReleaseJob).where(
        NarrativeReleaseJob.workflow_run_id.is_not(None),
        NarrativeReleaseJob.status.in_(("queued", "running")),
    )
    if after_id is not None:
        statement = statement.where(NarrativeReleaseJob.id > after_id)
    async with asyncio.timeout(min(10, pass_budget_seconds)):
        async with factory() as session:
            jobs = list(
                await session.scalars(statement.order_by(NarrativeReleaseJob.id).limit(limit))
            )
    recovered = inspected = 0
    for job in jobs:
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        inspected += 1
        run_id = job.workflow_run_id
        if run_id is None:
            continue
        scope = dict(tenant_id=job.tenant_id, release_id=job.release_id, job_id=job.id)
        payload = ReleasePayload(
            schema_version="1",
            tenant_id=str(job.tenant_id),
            release_id=str(job.release_id),
            job_id=str(job.id),
        )
        try:
            async with asyncio.timeout(min(10, remaining)):
                closed = await dispatcher.closed(payload, run_id=run_id)
            if not closed or loop.time() >= deadline:
                continue
            async with factory() as session:
                plan = await workflow_cleanup_plan(session, **scope, workflow_run_id=run_id)
                await session.commit()
            if plan is None:
                continue
            if plan.execution_token is not None:
                await builder.cleanup_execution(plan.execution_token)
            async with factory() as session:
                changed = await finalize_release_workflow(
                    session,
                    tenant_id=job.tenant_id,
                    release_id=job.release_id,
                    job_id=job.id,
                    workflow_run_id=run_id,
                    expected_token=plan.execution_token,
                    expected_attempt=plan.activity_attempt,
                )
                await session.commit()
            recovered += int(changed)
        except Exception:
            # Unknown Temporal state, changed ownership or unconfirmed physical
            # cleanup must leave the job for a later bounded pass. No raw log text.
            continue
    next_id = (
        jobs[inspected - 1].id
        if inspected and (inspected < len(jobs) or len(jobs) == limit)
        else None
    )
    return RecoveryBatch(inspected, recovered, next_id)


async def run_narrative_maintenance(
    factory: async_sessionmaker[AsyncSession],
    *,
    dispatcher: ClosedRunInspector,
    builder: MaintenanceCleaner,
    interval_seconds: float,
) -> None:
    """Independent loops keep Docker outages from delaying closed-run recovery."""
    if not 0.1 <= interval_seconds <= 3600:
        raise ValueError("Invalid narrative maintenance interval")
    logger = logging.getLogger(__name__)

    async def sweep_loop() -> None:
        while True:
            try:
                await builder.sweep_expired()
            except Exception:
                logger.warning("narrative owned cleanup unavailable")
            await asyncio.sleep(interval_seconds)

    async def recovery_loop() -> None:
        cursor = None
        while True:
            try:
                result = await recover_narrative_jobs(
                    factory, dispatcher=dispatcher, builder=builder, after_id=cursor
                )
                cursor = result.next_id
            except Exception:
                logger.warning("narrative closed-run recovery unavailable")
            await asyncio.sleep(interval_seconds)

    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(sweep_loop())
        tasks.create_task(recovery_loop())
