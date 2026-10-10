from uuid import uuid4

import pytest
from structlog.testing import capture_logs

from flint_graph.domain.enums import DocumentProjectionCleanupStatus
from flint_graph.infrastructure.db.models import DocumentProjectionCleanup
from flint_graph.processes import document_projection_cleanup as process


@pytest.mark.parametrize(
    "status,event,level",
    [
        (DocumentProjectionCleanupStatus.COMPLETED, "completed", "info"),
        (DocumentProjectionCleanupStatus.FAILED, "failed", "warning"),
        (DocumentProjectionCleanupStatus.RUNNING, "incomplete", "warning"),
        (DocumentProjectionCleanupStatus.PENDING, "incomplete", "warning"),
    ],
)
def test_cleanup_log_follows_ledger_status_without_provider_payload(
    status: DocumentProjectionCleanupStatus,
    event: str,
    level: str,
) -> None:
    cleanup = DocumentProjectionCleanup(
        id=uuid4(),
        status=status,
        attempt_count=2,
        error_code="PRIVATE_PROVIDER_MARKER",
        error_message="PRIVATE_PROVIDER_BODY",
    )
    with capture_logs() as logs:
        process.log_cleanup_outcome(cleanup)
    assert len(logs) == 1
    assert logs[0]["event"] == f"document_projection_cleanup.{event}"
    assert logs[0]["log_level"] == level
    assert logs[0]["status"] == status.value
    assert logs[0]["attempt_count"] == 2
    assert logs[0]["cleanup_id"] == str(cleanup.id)
    assert "PRIVATE" not in str(logs)


def test_iteration_error_log_does_not_dump_exception_payload() -> None:
    with capture_logs() as logs:
        process.log_cleanup_iteration_failure()
    assert logs == [
        {
            "event": "document_projection_cleanup.iteration_failed",
            "error_code": "cleanup_iteration_failed",
            "log_level": "warning",
        }
    ]
