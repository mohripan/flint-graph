"""Fenced release-attempt transitions; persistence supplies the locked active job.

These pure operations do not dispatch work or publish objects. Callers must hold
release -> job locks, persist state/events atomically and gate artifact insertion
on a *changed* transition to completed. A stale no-op never authorizes publication.
"""

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Literal
from uuid import UUID


class ReleaseJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ReleaseAttempt:
    id: UUID
    status: ReleaseJobStatus = ReleaseJobStatus.QUEUED
    cancel_requested: bool = False
    execution_token: UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ReleaseJobStatus):
            raise ValueError("Invalid release job status")
        if (self.status == ReleaseJobStatus.RUNNING) != (self.execution_token is not None):
            raise ValueError("Only a running release attempt may hold an execution token")
        if self.status == ReleaseJobStatus.COMPLETED and self.cancel_requested:
            raise ValueError("Cancelled work cannot be completed")


def claim_execution(state: ReleaseAttempt, *, token: UUID, active_job_id: UUID) -> ReleaseAttempt:
    """Fence a fresh activity execution, without reviving a terminal/old attempt.

    A recovery may rotate a running attempt's token. If cancel_requested is set,
    the new owner must finalize cancellation before launching any child.
    """
    if state.id != active_job_id or state.status not in (
        ReleaseJobStatus.QUEUED,
        ReleaseJobStatus.RUNNING,
    ):
        return state
    return replace(state, status=ReleaseJobStatus.RUNNING, execution_token=token)


def request_cancellation(state: ReleaseAttempt) -> ReleaseAttempt:
    """Linearize an API cancel request; running cleanup stays with its fenced owner."""
    if state.status == ReleaseJobStatus.QUEUED:
        return replace(state, status=ReleaseJobStatus.CANCELLED, cancel_requested=True)
    if state.status == ReleaseJobStatus.RUNNING:
        return replace(state, cancel_requested=True)
    return state


def finish_execution(
    state: ReleaseAttempt,
    *,
    token: UUID,
    active_job_id: UUID,
    outcome: Literal["completed", "failed", "cancelled"],
) -> ReleaseAttempt:
    """Only the active running owner can finish; cancellation wins before publish."""
    if outcome not in ("completed", "failed", "cancelled"):
        raise ValueError("Invalid release execution outcome")
    if (
        state.id != active_job_id
        or state.status != ReleaseJobStatus.RUNNING
        or state.execution_token != token
    ):
        return state
    cancelled = state.cancel_requested or outcome == "cancelled"
    return replace(
        state,
        status=ReleaseJobStatus.CANCELLED if cancelled else ReleaseJobStatus(outcome),
        cancel_requested=cancelled,
        execution_token=None,
    )
