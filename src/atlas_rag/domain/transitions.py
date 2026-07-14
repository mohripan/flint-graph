from atlas_rag.domain.enums import IngestionJobStatus, QueryRunStatus

_ALLOWED_JOB_TRANSITIONS: dict[IngestionJobStatus, set[IngestionJobStatus]] = {
    IngestionJobStatus.QUEUED: {
        IngestionJobStatus.RUNNING,
        IngestionJobStatus.CANCELLED,
        IngestionJobStatus.FAILED,
    },
    IngestionJobStatus.RUNNING: {
        IngestionJobStatus.COMPLETED,
        IngestionJobStatus.CANCELLED,
        IngestionJobStatus.FAILED,
    },
    IngestionJobStatus.COMPLETED: set(),
    IngestionJobStatus.FAILED: set(),
    IngestionJobStatus.CANCELLED: set(),
}


_ALLOWED_QUERY_RUN_TRANSITIONS: dict[QueryRunStatus, set[QueryRunStatus]] = {
    QueryRunStatus.QUEUED: {
        QueryRunStatus.RUNNING,
        QueryRunStatus.CANCELLED,
        QueryRunStatus.FAILED,
    },
    QueryRunStatus.RUNNING: {
        QueryRunStatus.COMPLETED,
        QueryRunStatus.CANCELLED,
        QueryRunStatus.FAILED,
    },
    QueryRunStatus.COMPLETED: set(),
    QueryRunStatus.FAILED: set(),
    QueryRunStatus.CANCELLED: set(),
}


def can_transition_job(
    current: IngestionJobStatus,
    target: IngestionJobStatus,
) -> bool:
    return target in _ALLOWED_JOB_TRANSITIONS[current]


def can_transition_query_run(
    current: QueryRunStatus,
    target: QueryRunStatus,
) -> bool:
    return target in _ALLOWED_QUERY_RUN_TRANSITIONS[current]
