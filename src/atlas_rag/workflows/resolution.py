from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

RESOLVE_ENTITIES_WORKFLOW = "ResolveEntitiesWorkflow"
RESOLVE_TENANT_ENTITIES_ACTIVITY = "resolve_tenant_entities"
ENQUEUE_TENANT_RESOLUTION_ACTIVITY = "enqueue_tenant_resolution"
REQUEST_RESOLUTION_SIGNAL = "request_resolution"

_RESOLUTION_ACTIVITY_TIMEOUT = timedelta(minutes=5)
_ACTIVITY_RETRY_POLICY = RetryPolicy(maximum_attempts=3)
_MAX_ITERATIONS_BEFORE_CONTINUE = 50


@workflow.defn(name=RESOLVE_ENTITIES_WORKFLOW)
class ResolveEntitiesWorkflow:
    """Per-tenant, single-writer entity resolution.

    Started via signal-with-start on the workflow id ``entity-resolution-{tenant}``
    so exactly one runs per tenant. Each signal marks work pending; the run drains
    pending mentions until no further request arrives, then completes. A new
    ingestion signals it again.
    """

    def __init__(self) -> None:
        self._requested = True

    @workflow.signal(name=REQUEST_RESOLUTION_SIGNAL)
    def request_resolution(self) -> None:
        self._requested = True

    @workflow.run
    async def run(self, tenant_id: str) -> None:
        iterations = 0
        while self._requested:
            self._requested = False
            await workflow.execute_activity(
                RESOLVE_TENANT_ENTITIES_ACTIVITY,
                tenant_id,
                start_to_close_timeout=_RESOLUTION_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY_POLICY,
            )
            iterations += 1
            if iterations >= _MAX_ITERATIONS_BEFORE_CONTINUE:
                workflow.continue_as_new(tenant_id)
