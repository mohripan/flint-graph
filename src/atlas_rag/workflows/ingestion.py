from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from atlas_rag.application.outbox_contracts import (
    IngestionFailurePayload,
    IngestionJobQueuedPayload,
)

MARK_JOB_RUNNING_ACTIVITY = "mark_ingestion_job_running"
RUN_STUB_INGESTION_ACTIVITY = "run_stub_ingestion"
MARK_JOB_COMPLETED_ACTIVITY = "mark_ingestion_job_completed"
MARK_JOB_FAILED_ACTIVITY = "mark_ingestion_job_failed"

_TRANSITION_ACTIVITY_TIMEOUT = timedelta(seconds=30)
_INGESTION_ACTIVITY_TIMEOUT = timedelta(minutes=5)
_ACTIVITY_RETRY_POLICY = RetryPolicy(maximum_attempts=3)


@workflow.defn(name="IngestDocumentWorkflow")
class IngestDocumentWorkflow:
    @workflow.run
    async def run(self, payload: IngestionJobQueuedPayload) -> None:
        await workflow.execute_activity(
            MARK_JOB_RUNNING_ACTIVITY,
            payload,
            start_to_close_timeout=_TRANSITION_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY_POLICY,
        )
        try:
            await workflow.execute_activity(
                RUN_STUB_INGESTION_ACTIVITY,
                payload,
                start_to_close_timeout=_INGESTION_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY_POLICY,
            )
            await workflow.execute_activity(
                MARK_JOB_COMPLETED_ACTIVITY,
                payload,
                start_to_close_timeout=_TRANSITION_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY_POLICY,
            )
        except Exception as exc:
            failure_payload = IngestionFailurePayload(
                payload=payload,
                error_code="ingestion_failed",
                error_message=str(exc),
            )
            await workflow.execute_activity(
                MARK_JOB_FAILED_ACTIVITY,
                failure_payload,
                start_to_close_timeout=_TRANSITION_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY_POLICY,
            )
            raise
