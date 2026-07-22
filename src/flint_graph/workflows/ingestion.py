from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import CancelledError

from flint_graph.application.outbox_contracts import (
    IndexDocumentVersionPayload,
    IngestionFailurePayload,
    IngestionJobQueuedPayload,
    PreparedDocumentIndexingPayload,
)
from flint_graph.workflows.indexing import INDEX_DOCUMENT_VERSION_WORKFLOW
from flint_graph.workflows.resolution import ENQUEUE_TENANT_RESOLUTION_ACTIVITY

MARK_JOB_RUNNING_ACTIVITY = "mark_ingestion_job_running"
RUN_INGESTION_PIPELINE_ACTIVITY = "run_ingestion_pipeline"
PREPARE_DOCUMENT_INDEXING_ACTIVITY = "prepare_document_indexing"
ENQUEUE_DOCUMENT_INDEXING_ACTIVITY = "enqueue_document_indexing"
MARK_JOB_COMPLETED_ACTIVITY = "mark_ingestion_job_completed"
MARK_JOB_FAILED_ACTIVITY = "mark_ingestion_job_failed"
MARK_JOB_CANCELLED_ACTIVITY = "mark_ingestion_job_cancelled"

_TRANSITION_ACTIVITY_TIMEOUT = timedelta(seconds=30)
_INGESTION_ACTIVITY_TIMEOUT = timedelta(minutes=5)
_ACTIVITY_RETRY_POLICY = RetryPolicy(maximum_attempts=3)


@workflow.defn(name="IngestDocumentWorkflow")
class IngestDocumentWorkflow:
    @workflow.run
    async def run(self, payload: IngestionJobQueuedPayload) -> None:
        optional_indexing_payload: IndexDocumentVersionPayload | None = None
        await workflow.execute_activity(
            MARK_JOB_RUNNING_ACTIVITY,
            payload,
            start_to_close_timeout=_TRANSITION_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY_POLICY,
        )
        try:
            await workflow.execute_activity(
                RUN_INGESTION_PIPELINE_ACTIVITY,
                payload,
                start_to_close_timeout=_INGESTION_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY_POLICY,
            )
            prepared_indexing: PreparedDocumentIndexingPayload = (
                await workflow.execute_activity(
                    PREPARE_DOCUMENT_INDEXING_ACTIVITY,
                    payload,
                    start_to_close_timeout=_TRANSITION_ACTIVITY_TIMEOUT,
                    retry_policy=_ACTIVITY_RETRY_POLICY,
                )
            )
            if prepared_indexing["should_index"]:
                indexing_payload = prepared_indexing.get("payload")
                if indexing_payload is None:
                    raise RuntimeError("indexing preparation omitted payload")
                if prepared_indexing["mode"] == "required":
                    await workflow.execute_child_workflow(
                        INDEX_DOCUMENT_VERSION_WORKFLOW,
                        indexing_payload,
                        id=(
                            "index-document-version-"
                            f"{indexing_payload['document_version_id']}-"
                            f"{indexing_payload['retrieval_index_version_id']}"
                        ),
                    )
                elif prepared_indexing["mode"] == "optional":
                    optional_indexing_payload = indexing_payload
            await workflow.execute_activity(
                MARK_JOB_COMPLETED_ACTIVITY,
                payload,
                start_to_close_timeout=_TRANSITION_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY_POLICY,
            )
        except CancelledError:
            await workflow.execute_activity(
                MARK_JOB_CANCELLED_ACTIVITY,
                payload,
                start_to_close_timeout=_TRANSITION_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY_POLICY,
            )
            raise
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

        # The job is committed as completed; trigger per-tenant resolution as an
        # isolated best-effort step so its failure cannot re-fail a completed job.
        if optional_indexing_payload is not None:
            await workflow.execute_activity(
                ENQUEUE_DOCUMENT_INDEXING_ACTIVITY,
                optional_indexing_payload,
                start_to_close_timeout=_TRANSITION_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY_POLICY,
            )
        await workflow.execute_activity(
            ENQUEUE_TENANT_RESOLUTION_ACTIVITY,
            payload["tenant_id"],
            start_to_close_timeout=_TRANSITION_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY_POLICY,
        )
