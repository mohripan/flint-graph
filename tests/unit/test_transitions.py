from flint_graph.domain.enums import IngestionJobStatus
from flint_graph.domain.transitions import can_transition_job


def test_job_transition_rules_are_terminal_after_completion() -> None:
    assert can_transition_job(IngestionJobStatus.QUEUED, IngestionJobStatus.RUNNING)
    assert can_transition_job(IngestionJobStatus.RUNNING, IngestionJobStatus.COMPLETED)
    assert not can_transition_job(IngestionJobStatus.COMPLETED, IngestionJobStatus.RUNNING)