"""Deterministic music job supervision (ADR 0067); descriptions and audio stay in activities."""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, CancelledError

from flint_graph.application.narrative_image_workflow import (
    FINALIZE_MUSIC_ACTIVITY,
    FINALIZE_MUSIC_ACTIVITY_ID,
    MUSIC_WORKFLOW,
    RUN_MUSIC_ACTIVITY,
    RUN_MUSIC_ACTIVITY_ID,
    ImageJobOutcome,
    ImageJobPayload,
    music_job_workflow_id,
    validate_image_outcome,
    validate_image_payload,
)

# A busy GPU and a not-yet-committed run registration retry; the activity itself
# fails the job on its final attempt with a safe code.
_RUN_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=10), backoff_coefficient=2.0, maximum_attempts=3
)
_FINALIZE_RETRY = RetryPolicy(initial_interval=timedelta(seconds=1), maximum_attempts=5)


@workflow.defn(name=MUSIC_WORKFLOW)
class NarrativeMusicJobWorkflow:
    @workflow.run
    async def run(self, payload: ImageJobPayload) -> ImageJobOutcome:
        try:
            data = validate_image_payload(payload)
            if workflow.info().workflow_id != music_job_workflow_id(data):
                raise ValueError
        except ValueError:
            raise ApplicationError("workflow_identity", non_retryable=True) from None
        try:
            result = await workflow.execute_activity(
                RUN_MUSIC_ACTIVITY,
                data,
                activity_id=RUN_MUSIC_ACTIVITY_ID,
                start_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=timedelta(seconds=60),
                retry_policy=_RUN_RETRY,
                cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            )
            return validate_image_outcome(result, job_id=data["job_id"])
        except (asyncio.CancelledError, CancelledError, ActivityError, ValueError) as exc:
            cancelled = isinstance(exc, (asyncio.CancelledError, CancelledError)) or (
                isinstance(exc, ActivityError) and isinstance(exc.cause, CancelledError)
            )
            # The finalizer closes an abandoned job of this run; it must survive
            # repeated cancellation in either exception representation.
            finalizer = workflow.start_activity(
                FINALIZE_MUSIC_ACTIVITY,
                {**data, "cancelled": cancelled},
                activity_id=FINALIZE_MUSIC_ACTIVITY_ID,
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
                return validate_image_outcome(result, job_id=data["job_id"])
            except ValueError:
                raise ApplicationError("result_identity", non_retryable=True) from None
