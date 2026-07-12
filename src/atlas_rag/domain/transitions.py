from atlas_rag.domain.enums import IngestionJobStatus

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

def can_transition_job(
    current: IngestionJobStatus,
    target: IngestionJobStatus,
) -> bool:
    return target in _ALLOWED_JOB_TRANSITIONS[current]