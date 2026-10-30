"""Publication/cancellation races at the release-attempt transition boundary."""

from uuid import uuid4

from flint_graph.application.narrative_release_state import (
    ReleaseAttempt,
    ReleaseJobStatus,
    claim_execution,
    finish_execution,
    request_cancellation,
)


def test_cancel_before_dispatch_cannot_be_revived_by_a_late_worker() -> None:
    queued = ReleaseAttempt(id=uuid4())
    cancelled = request_cancellation(queued)
    assert cancelled.status == ReleaseJobStatus.CANCELLED
    assert cancelled.execution_token is None
    assert claim_execution(cancelled, token=uuid4(), active_job_id=queued.id) == cancelled


def test_running_cancellation_prevents_publication_and_revokes_the_execution() -> None:
    queued = ReleaseAttempt(id=uuid4())
    token = uuid4()
    running = claim_execution(queued, token=token, active_job_id=queued.id)
    pending = request_cancellation(running)
    assert pending.status == ReleaseJobStatus.RUNNING
    assert pending.cancel_requested
    stopped = finish_execution(pending, token=token, active_job_id=queued.id, outcome="completed")
    assert stopped.status == ReleaseJobStatus.CANCELLED
    assert stopped.execution_token is None
    assert (
        finish_execution(stopped, token=token, active_job_id=queued.id, outcome="completed")
        == stopped
    )


def test_a_replacement_execution_fences_both_old_publication_and_old_cleanup() -> None:
    queued = ReleaseAttempt(id=uuid4())
    first, replacement = uuid4(), uuid4()
    old = claim_execution(queued, token=first, active_job_id=queued.id)
    current = claim_execution(old, token=replacement, active_job_id=queued.id)
    for outcome in ["completed", "failed", "cancelled"]:
        assert (
            finish_execution(current, token=first, active_job_id=queued.id, outcome=outcome)
            == current
        )
    assert current.execution_token == replacement
    completed = finish_execution(
        current, token=replacement, active_job_id=queued.id, outcome="completed"
    )
    assert completed.status == ReleaseJobStatus.COMPLETED
    assert completed.execution_token is None
    assert request_cancellation(completed) == completed
    assert (
        finish_execution(completed, token=replacement, active_job_id=queued.id, outcome="failed")
        == completed
    )


def test_failed_attempt_cannot_publish_after_an_explicit_new_job_was_created() -> None:
    queued = ReleaseAttempt(id=uuid4())
    token, newer_job_id = uuid4(), uuid4()
    running = claim_execution(queued, token=token, active_job_id=queued.id)
    failed = finish_execution(running, token=token, active_job_id=queued.id, outcome="failed")
    assert failed.status == ReleaseJobStatus.FAILED
    assert failed.execution_token is None
    assert claim_execution(failed, token=uuid4(), active_job_id=newer_job_id) == failed
    assert (
        finish_execution(running, token=token, active_job_id=newer_job_id, outcome="completed")
        == running
    )


def test_publication_committed_before_cancel_remains_a_completed_release() -> None:
    queued = ReleaseAttempt(id=uuid4())
    token = uuid4()
    running = claim_execution(queued, token=token, active_job_id=queued.id)
    published = finish_execution(running, token=token, active_job_id=queued.id, outcome="completed")
    assert published.status == ReleaseJobStatus.COMPLETED
    assert not published.cancel_requested
    assert request_cancellation(published) == published
    assert claim_execution(published, token=uuid4(), active_job_id=queued.id) == published


def test_recovered_cancelled_execution_can_finish_cleanup_without_starting_a_new_build() -> None:
    queued = ReleaseAttempt(id=uuid4())
    old_token, recovery_token = uuid4(), uuid4()
    running = claim_execution(queued, token=old_token, active_job_id=queued.id)
    pending = request_cancellation(running)
    recovered = claim_execution(pending, token=recovery_token, active_job_id=queued.id)
    assert recovered.cancel_requested
    assert recovered.execution_token == recovery_token
    assert (
        finish_execution(recovered, token=old_token, active_job_id=queued.id, outcome="failed")
        == recovered
    )
    cleaned = finish_execution(
        recovered, token=recovery_token, active_job_id=queued.id, outcome="failed"
    )
    assert cleaned.status == ReleaseJobStatus.CANCELLED
    assert cleaned.execution_token is None
