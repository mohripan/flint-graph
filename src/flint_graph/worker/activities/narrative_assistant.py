"""Assistant activity edge: model calls and story text stay here; history gets IDs/status.

Streamed steps, thinking and reply text are written to PostgreSQL by a fenced
``TurnEventWriter``; a lost fence or a requested stop ends the model call early.
"""

import asyncio
from contextlib import suppress
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio import activity
from temporalio.exceptions import ApplicationError

from flint_graph.application.narrative_assistant_workflow import (
    FINALIZE_TURN_ACTIVITY,
    RUN_TURN_ACTIVITY,
    TURN_WORKFLOW,
    FinalizePayload,
    TurnOutcome,
    TurnPayload,
    turn_workflow_id,
    validate_turn_payload,
)
from flint_graph.application.services.narrative_assistant import (
    TurnRegistrationPending,
    abandon_turn,
    claim_turn,
    complete_turn,
    fail_turn,
)
from flint_graph.application.services.narrative_assistant_events import TurnEventWriter
from flint_graph.infrastructure.db.models import NarrativeAssistantTurn
from flint_graph.narrative.assistant.turn import AssistantModel, AssistantModelError, run_turn

_TRANSIENT = {"provider_unavailable", "provider_timeout"}
_TERMINAL = ("completed", "failed", "cancelled")


def _outcome(turn_id: UUID, turn: NarrativeAssistantTurn | None) -> TurnOutcome:
    status = turn.status if turn is not None and turn.status in _TERMINAL else "stale"
    return cast(TurnOutcome, {"turn_id": str(turn_id), "status": status})


async def _heartbeat() -> None:
    while True:
        activity.heartbeat()
        await asyncio.sleep(5)


class NarrativeAssistantActivities:
    def __init__(
        self,
        *,
        factory: async_sessionmaker[AsyncSession],
        model: AssistantModel | None,
        context_chars: int,
        max_attempts: int = 3,
    ) -> None:
        self.factory, self.model = factory, model
        self.context_chars, self.max_attempts = context_chars, max_attempts

    @staticmethod
    def _context(payload: object, *, finalizer: bool = False) -> tuple[TurnPayload, UUID, int]:
        try:
            data = validate_turn_payload(payload)
            info = activity.info()
            run_id = UUID(info.workflow_run_id or "")
            if (
                info.workflow_id != turn_workflow_id(data)
                or info.workflow_type != TURN_WORKFLOW
                or info.activity_type
                != (FINALIZE_TURN_ACTIVITY if finalizer else RUN_TURN_ACTIVITY)
                or info.is_local
                or type(info.attempt) is not int
                or info.attempt < 1
                or str(run_id) != info.workflow_run_id
            ):
                raise ValueError
            return data, run_id, info.attempt
        except Exception:
            raise ApplicationError("activity_identity", non_retryable=True) from None

    async def _fail(self, turn_id: UUID, token: UUID, code: str) -> TurnOutcome:
        async with self.factory() as session:
            turn = await fail_turn(session, turn_id=turn_id, execution_token=token, error_code=code)
            await session.commit()
        return _outcome(turn_id, turn)

    @activity.defn(name=RUN_TURN_ACTIVITY)
    async def run(self, payload: TurnPayload) -> TurnOutcome:
        data, run_id, attempt = self._context(payload)
        turn_id, token = UUID(data["turn_id"]), uuid4()
        try:
            async with self.factory() as session:
                work = await claim_turn(
                    session,
                    turn_id=turn_id,
                    execution_token=token,
                    workflow_run_id=run_id,
                    activity_attempt=attempt,
                )
                await session.commit()
        except TurnRegistrationPending:
            raise ApplicationError("registration_pending", type="registration_pending") from None
        if work is None:
            return _outcome(turn_id, None)
        if self.model is None:
            return await self._fail(turn_id, token, "assistant_unavailable")
        beating = asyncio.create_task(_heartbeat())
        # Live progress goes straight to PostgreSQL; Temporal only sees IDs and status.
        events = TurnEventWriter(self.factory, turn_id=turn_id, execution_token=token)
        try:
            result = await run_turn(
                self.model,
                work.story,
                work.request,
                focus=work.focus,
                history=work.history,
                budget=self.context_chars,
                observer=events,
            )
            await events.flush()
        except AssistantModelError as error:
            if error.code in _TRANSIENT and attempt < self.max_attempts:
                # The turn stays running; the next attempt of this run replaces the token.
                raise ApplicationError(error.code, type=error.code) from None
            return await self._fail(turn_id, token, error.code)
        except asyncio.CancelledError:
            cleanup = asyncio.create_task(self._fail(turn_id, token, "cancelled"))
            while not cleanup.done():
                with suppress(asyncio.CancelledError):
                    await asyncio.shield(cleanup)
            raise
        except Exception:
            return await self._fail(turn_id, token, "assistant_failed")
        finally:
            beating.cancel()
            with suppress(asyncio.CancelledError):
                await beating
        async with self.factory() as session:
            turn = await complete_turn(
                session,
                turn_id=turn_id,
                execution_token=token,
                result=result,
                provider=self.model.provider,
            )
            await session.commit()
        return _outcome(turn_id, turn)

    @activity.defn(name=FINALIZE_TURN_ACTIVITY)
    async def finalize(self, payload: FinalizePayload) -> TurnOutcome:
        cancelled = payload.get("cancelled") if isinstance(payload, dict) else None
        if type(cancelled) is not bool:
            raise ApplicationError("activity_identity", non_retryable=True)
        base = {key: value for key, value in payload.items() if key != "cancelled"}
        data, run_id, _ = self._context(base, finalizer=True)
        turn_id = UUID(data["turn_id"])
        async with self.factory() as session:
            turn = await abandon_turn(
                session,
                turn_id=turn_id,
                workflow_run_id=run_id,
                error_code="cancelled" if cancelled else "worker_interrupted",
            )
            await session.commit()
        return _outcome(turn_id, turn)
