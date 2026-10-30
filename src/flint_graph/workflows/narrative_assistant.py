"""Deterministic supervision only; requests, replies and story text stay in activities."""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, CancelledError

from flint_graph.application.narrative_assistant_workflow import (
    FINALIZE_ACTIVITY_ID,
    FINALIZE_TURN_ACTIVITY,
    RUN_ACTIVITY_ID,
    RUN_TURN_ACTIVITY,
    TURN_WORKFLOW,
    TurnOutcome,
    TurnPayload,
    turn_workflow_id,
    validate_turn_outcome,
    validate_turn_payload,
)

# Transient provider errors and a not-yet-committed run registration retry; the
# activity itself fails the turn on its final attempt with a safe code.
_RUN_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2), backoff_coefficient=2.0, maximum_attempts=3
)
_FINALIZE_RETRY = RetryPolicy(initial_interval=timedelta(seconds=1), maximum_attempts=5)


@workflow.defn(name=TURN_WORKFLOW)
class NarrativeAssistantTurnWorkflow:
    @workflow.run
    async def run(self, payload: TurnPayload) -> TurnOutcome:
        try:
            data = validate_turn_payload(payload)
            if workflow.info().workflow_id != turn_workflow_id(data):
                raise ValueError
        except ValueError:
            raise ApplicationError("workflow_identity", non_retryable=True) from None
        try:
            result = await workflow.execute_activity(
                RUN_TURN_ACTIVITY,
                data,
                activity_id=RUN_ACTIVITY_ID,
                start_to_close_timeout=timedelta(minutes=10),
                heartbeat_timeout=timedelta(seconds=30),
                retry_policy=_RUN_RETRY,
                cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            )
            return validate_turn_outcome(result, turn_id=data["turn_id"])
        except (asyncio.CancelledError, CancelledError, ActivityError, ValueError) as exc:
            cancelled = isinstance(exc, (asyncio.CancelledError, CancelledError)) or (
                isinstance(exc, ActivityError) and isinstance(exc.cause, CancelledError)
            )
            # The finalizer closes an abandoned turn of this run; it must survive
            # repeated cancellation in either exception representation.
            finalizer = workflow.start_activity(
                FINALIZE_TURN_ACTIVITY,
                {**data, "cancelled": cancelled},
                activity_id=FINALIZE_ACTIVITY_ID,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=_FINALIZE_RETRY,
            )
            while not finalizer.done():
                try:
                    await asyncio.shield(finalizer)
                except asyncio.CancelledError:
                    cancelled = True
            result = finalizer.result()
            if cancelled:
                raise asyncio.CancelledError from None
            try:
                return validate_turn_outcome(result, turn_id=data["turn_id"])
            except ValueError:
                raise ApplicationError("result_identity", non_retryable=True) from None
