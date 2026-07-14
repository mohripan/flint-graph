from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import CancelledError

from atlas_rag.application.outbox_contracts import (
    BackfillDocumentFailurePayload,
    IndexBackfillPayload,
)
from atlas_rag.workflows.indexing import INDEX_DOCUMENT_VERSION_WORKFLOW

INDEX_BACKFILL_WORKFLOW = "IndexBackfillWorkflow"
MARK_INDEX_BACKFILL_RUNNING_ACTIVITY = "mark_index_backfill_running"
LOAD_INDEX_BACKFILL_BATCH_ACTIVITY = "load_index_backfill_batch"
MARK_INDEX_BACKFILL_DOCUMENT_COMPLETED_ACTIVITY = "mark_index_backfill_document_completed"
MARK_INDEX_BACKFILL_DOCUMENT_FAILED_ACTIVITY = "mark_index_backfill_document_failed"
COMPLETE_INDEX_BACKFILL_ACTIVITY = "complete_index_backfill"
FAIL_INDEX_BACKFILL_ACTIVITY = "fail_index_backfill"
MARK_INDEX_BACKFILL_CANCELLED_ACTIVITY = "mark_index_backfill_cancelled"

_TRANSITION_ACTIVITY_TIMEOUT = timedelta(seconds=30)
_SCAN_ACTIVITY_TIMEOUT = timedelta(minutes=2)
_ACTIVITY_RETRY_POLICY = RetryPolicy(maximum_attempts=3)


@workflow.defn(name=INDEX_BACKFILL_WORKFLOW)
class IndexBackfillWorkflow:
    @workflow.run
    async def run(self, payload: IndexBackfillPayload) -> None:
        failed = False
        await workflow.execute_activity(
            MARK_INDEX_BACKFILL_RUNNING_ACTIVITY,
            payload,
            start_to_close_timeout=_TRANSITION_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY_POLICY,
        )
        try:
            while True:
                batch = await workflow.execute_activity(
                    LOAD_INDEX_BACKFILL_BATCH_ACTIVITY,
                    payload,
                    start_to_close_timeout=_SCAN_ACTIVITY_TIMEOUT,
                    retry_policy=_ACTIVITY_RETRY_POLICY,
                )
                documents = list(batch["documents"])
                if not documents and batch["done"]:
                    break

                for document_payload in documents:
                    try:
                        await workflow.execute_child_workflow(
                            INDEX_DOCUMENT_VERSION_WORKFLOW,
                            document_payload,
                            id=(
                                "index-document-version-"
                                f"{document_payload['document_version_id']}-"
                                f"{document_payload['retrieval_index_version_id']}"
                            ),
                        )
                        await workflow.execute_activity(
                            MARK_INDEX_BACKFILL_DOCUMENT_COMPLETED_ACTIVITY,
                            {
                                "backfill_job_id": payload["backfill_job_id"],
                                "document_version_id": document_payload[
                                    "document_version_id"
                                ],
                            },
                            start_to_close_timeout=_TRANSITION_ACTIVITY_TIMEOUT,
                            retry_policy=_ACTIVITY_RETRY_POLICY,
                        )
                    except Exception as exc:
                        failed = True
                        failure_payload = BackfillDocumentFailurePayload(
                            backfill_job_id=payload["backfill_job_id"],
                            document_version_id=document_payload[
                                "document_version_id"
                            ],
                            error_code="indexing_failed",
                            error_message=str(exc),
                        )
                        await workflow.execute_activity(
                            MARK_INDEX_BACKFILL_DOCUMENT_FAILED_ACTIVITY,
                            failure_payload,
                            start_to_close_timeout=_TRANSITION_ACTIVITY_TIMEOUT,
                            retry_policy=_ACTIVITY_RETRY_POLICY,
                        )

            final_activity = (
                FAIL_INDEX_BACKFILL_ACTIVITY if failed else COMPLETE_INDEX_BACKFILL_ACTIVITY
            )
            await workflow.execute_activity(
                final_activity,
                payload,
                start_to_close_timeout=_TRANSITION_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY_POLICY,
            )
        except CancelledError:
            await workflow.execute_activity(
                MARK_INDEX_BACKFILL_CANCELLED_ACTIVITY,
                payload,
                start_to_close_timeout=_TRANSITION_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY_POLICY,
            )
            raise
