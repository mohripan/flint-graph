import pytest

from flint_graph.application.outbox_contracts import IngestionJobQueuedPayload
from flint_graph.config import Settings
from flint_graph.worker.activities.indexing import prepare_document_indexing_for_payload


def _payload() -> IngestionJobQueuedPayload:
    return {
        "tenant_id": "6bcb4c0b-f90f-4b9c-9796-f12fcd89707c",
        "document_id": "9f26f9b0-fdb4-4d9e-b544-3299b3d8b64c",
        "document_version_id": "749c7dc0-cb96-458e-8096-17c2e098a3fb",
        "ingestion_job_id": "be45f762-674b-40b5-9200-271c48078d76",
        "idempotency_key": "workflow-test",
        "source_type": "url",
        "source_uri": "https://example.test/workflow",
        "trace_context": {},
    }


async def test_optional_indexing_preparation_skips_invalid_configured_index_id() -> None:
    prepared = await prepare_document_indexing_for_payload(
        _payload(),
        settings=Settings(
            indexing_mode="optional",
            active_retrieval_index_version_id="not-a-uuid",
        ),
    )

    assert prepared == {"mode": "optional", "should_index": False}


async def test_required_indexing_preparation_raises_invalid_configured_index_id() -> None:
    with pytest.raises(ValueError):
        await prepare_document_indexing_for_payload(
            _payload(),
            settings=Settings(
                indexing_mode="required",
                active_retrieval_index_version_id="not-a-uuid",
            ),
        )
