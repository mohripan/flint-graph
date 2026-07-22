from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import CancelledError

from flint_graph.application.outbox_contracts import (
    DocumentIndexingFailurePayload,
    IndexDocumentVersionPayload,
)

INDEX_DOCUMENT_VERSION_WORKFLOW = "IndexDocumentVersionWorkflow"
PLAN_DOCUMENT_INDEXING_ACTIVITY = "plan_document_indexing"
INDEX_DOCUMENT_BATCH_ACTIVITY = "index_document_batch"
MARK_INDEXING_COMPLETED_ACTIVITY = "mark_document_indexing_completed"
MARK_INDEXING_FAILED_ACTIVITY = "mark_document_indexing_failed"
MARK_INDEXING_CANCELLED_ACTIVITY = "mark_document_indexing_cancelled"

_INDEXING_ACTIVITY_TIMEOUT = timedelta(minutes=5)
_TRANSITION_ACTIVITY_TIMEOUT = timedelta(seconds=30)
_ACTIVITY_RETRY_POLICY = RetryPolicy(maximum_attempts=3)


@workflow.defn(name=INDEX_DOCUMENT_VERSION_WORKFLOW)
class IndexDocumentVersionWorkflow:
    @workflow.run
    async def run(self, payload: IndexDocumentVersionPayload) -> None:
        try:
            plan = await workflow.execute_activity(
                PLAN_DOCUMENT_INDEXING_ACTIVITY,
                payload,
                start_to_close_timeout=_TRANSITION_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY_POLICY,
            )
            batch_count = int(plan["batch_count"])
            for batch_index in range(batch_count):
                batch_payload: dict[str, Any] = dict(payload)
                batch_payload["batch_index"] = batch_index
                await workflow.execute_activity(
                    INDEX_DOCUMENT_BATCH_ACTIVITY,
                    batch_payload,
                    start_to_close_timeout=_INDEXING_ACTIVITY_TIMEOUT,
                    retry_policy=_ACTIVITY_RETRY_POLICY,
                )
            await workflow.execute_activity(
                MARK_INDEXING_COMPLETED_ACTIVITY,
                payload,
                start_to_close_timeout=_TRANSITION_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY_POLICY,
            )
        except CancelledError:
            await workflow.execute_activity(
                MARK_INDEXING_CANCELLED_ACTIVITY,
                payload,
                start_to_close_timeout=_TRANSITION_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY_POLICY,
            )
            raise
        except Exception as exc:
            failure_payload = DocumentIndexingFailurePayload(
                payload=payload,
                error_code="indexing_failed",
                error_message=str(exc),
            )
            await workflow.execute_activity(
                MARK_INDEXING_FAILED_ACTIVITY,
                failure_payload,
                start_to_close_timeout=_TRANSITION_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY_POLICY,
            )
            raise
