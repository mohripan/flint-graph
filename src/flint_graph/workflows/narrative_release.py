"""Deterministic supervision only; private source and artifact bytes stay in activities."""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, CancelledError

from flint_graph.application.narrative_workflow import (
    BUILD_ACTIVITY_ID,
    BUILD_NARRATIVE_RELEASE_ACTIVITY,
    FINALIZE_ACTIVITY_ID,
    FINALIZE_NARRATIVE_RELEASE_ACTIVITY,
    NARRATIVE_RELEASE_WORKFLOW,
    ReleasePayload,
    ReleaseResult,
    release_workflow_id,
    validate_release_payload,
    validate_release_result,
)

_RETRY = RetryPolicy(initial_interval=timedelta(seconds=1), maximum_attempts=3)


@workflow.defn(name=NARRATIVE_RELEASE_WORKFLOW)
class NarrativeReleaseWorkflow:
    @workflow.run
    async def run(self, payload: ReleasePayload) -> ReleaseResult:
        try:
            data = validate_release_payload(payload)
            if workflow.info().workflow_id != release_workflow_id(data):
                raise ValueError
        except ValueError:
            raise ApplicationError("workflow_identity", non_retryable=True) from None
        try:
            result = await workflow.execute_activity(
                BUILD_NARRATIVE_RELEASE_ACTIVITY,
                data,
                activity_id=BUILD_ACTIVITY_ID,
                start_to_close_timeout=timedelta(minutes=5),
                heartbeat_timeout=timedelta(seconds=10),
                retry_policy=_RETRY,
                cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            )
            return validate_release_result(result, job_id=data["job_id"])
        except (asyncio.CancelledError, CancelledError, ActivityError, ValueError) as exc:
            cancelled = isinstance(exc, (asyncio.CancelledError, CancelledError)) or (
                isinstance(exc, ActivityError) and isinstance(exc.cause, CancelledError)
            )
            # WAIT_CANCELLATION_COMPLETED surfaces cancellation as ActivityError
            # with a CancelledError cause in the current SDK. Finalization must
            # survive repeated cancellation in either exception representation.
            finalizer = workflow.start_activity(
                FINALIZE_NARRATIVE_RELEASE_ACTIVITY,
                {**data, "cancelled": cancelled},
                activity_id=FINALIZE_ACTIVITY_ID,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=_RETRY,
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
                return validate_release_result(result, job_id=data["job_id"])
            except ValueError:
                raise ApplicationError("result_identity", non_retryable=True) from None
