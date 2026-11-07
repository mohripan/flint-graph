"""The durable state of a proposal's generation actions (ADR 0061).

These helpers only write state; ``narrative_assistant_actions`` starts the jobs. They
live apart because the turn and proposal services need them, and job admission needs
those services in turn.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.narrative_assistant_log import append_thread_event
from flint_graph.infrastructure.db.models import NarrativeAsset
from flint_graph.infrastructure.db.narrative_assistant_models import (
    NarrativeAssistantAction,
    NarrativeAssistantProposal,
    NarrativeAssistantTurn,
)
from flint_graph.narrative.assistant.log import ASSET_APPROVED
from flint_graph.narrative.assistant.operations import ACTIONS, Operation

OFFERED = "offered"  # Shows its card, and waits for the creator to press Generate (ADR 0068).
PENDING = "pending"  # Pressed with the queue full; the dispatcher starts it when there is room.
STARTED = "started"  # Bound to a job.
BLOCKED = "blocked"  # Could not start; says why, and a press retries it.
FINISHED = "finished"  # Its job ended, and the thread log says how.
SKIPPED = "skipped"  # The proposal was rejected first.
DECLINED = "declined"  # The creator pressed Cancel; they can still change their mind.

_OPEN = (OFFERED, PENDING, BLOCKED)


async def create_actions(
    session: AsyncSession,
    *,
    turn: NarrativeAssistantTurn,
    proposal: NarrativeAssistantProposal,
    operations: Sequence[Operation],
) -> None:
    for index, operation in enumerate(operations):
        if not isinstance(operation, ACTIONS):
            continue
        session.add(
            NarrativeAssistantAction(
                tenant_id=proposal.tenant_id,
                project_id=proposal.project_id,
                thread_id=proposal.thread_id,
                proposal_id=proposal.id,
                op_index=index,
                op=operation.op,
                author_user_id=turn.author_user_id,
                status=OFFERED,
            )
        )
    await session.flush()


async def skip_open_actions(session: AsyncSession, proposal_id: UUID) -> None:
    """Rejecting a proposal stops what has not started; running jobs finish normally."""
    await session.execute(
        update(NarrativeAssistantAction)
        .where(
            NarrativeAssistantAction.proposal_id == proposal_id,
            NarrativeAssistantAction.status.in_(_OPEN),
        )
        .values(status=SKIPPED)
    )


async def note_asset_approved(
    session: AsyncSession, asset: NarrativeAsset, author_user_id: UUID
) -> None:
    """Tell the conversation that started a job which of its results the creator chose."""
    if asset.job_id is not None:
        match = NarrativeAssistantAction.image_job_id == asset.job_id
    elif asset.voice_job_id is not None:
        match = NarrativeAssistantAction.voice_job_id == asset.voice_job_id
    else:
        return
    action = await session.scalar(
        select(NarrativeAssistantAction).where(
            NarrativeAssistantAction.tenant_id == asset.tenant_id,
            NarrativeAssistantAction.project_id == asset.project_id,
            match,
        )
    )
    if action is None:
        return
    await append_thread_event(
        session,
        tenant_id=action.tenant_id,
        project_id=action.project_id,
        thread_id=action.thread_id,
        kind=ASSET_APPROVED,
        payload={
            "proposal_id": str(action.proposal_id),
            "index": action.op_index,
            "asset_id": str(asset.id),
            "name": asset.name,
            "kind": asset.kind,
        },
        actor_user_id=author_user_id,
    )
