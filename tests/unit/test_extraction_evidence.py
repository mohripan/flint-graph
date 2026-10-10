from uuid import UUID

import pytest

from flint_graph.application.extraction_evidence import (
    EvidenceResolutionError,
    resolve_batch_evidence,
)
from flint_graph.application.extraction_proposals import (
    EvidenceProposal,
    ExtractedEntityProposal,
    ExtractedRelationProposal,
    ExtractionBatch,
    ExtractionInputChunk,
)

VERSION_ID = UUID("87c13861-d4e4-4a75-9708-7b92b35a13e0")


def test_resolve_batch_evidence_calculates_offsets_hashes_and_links() -> None:
    batch = ExtractionBatch(
        input_chunk_ids=["chunk-000001"],
        entities=[
            ExtractedEntityProposal(
                local_id="e1",
                name="Acme Corporation",
                entity_type="organization",
                evidence=[
                    EvidenceProposal(chunk_id="chunk-000001", quote="Acme Corporation")
                ],
            ),
            ExtractedEntityProposal(
                local_id="e2",
                name="Berlin",
                entity_type="place",
                evidence=[EvidenceProposal(chunk_id="chunk-000001", quote="Berlin")],
            ),
        ],
        relations=[
            ExtractedRelationProposal(
                local_id="r1",
                subject_entity_id="e1",
                predicate="headquartered_in",
                object_entity_id="e2",
                evidence=[
                    EvidenceProposal(
                        chunk_id="chunk-000001",
                        quote="Acme Corporation is headquartered in Berlin",
                    )
                ],
            )
        ],
    )

    resolved = resolve_batch_evidence(
        batch,
        document_version_id=VERSION_ID,
        chunks=[
            ExtractionInputChunk(
                chunk_id="chunk-000001",
                text="Acme Corporation is headquartered in Berlin.",
            )
        ],
    )

    acme_span = resolved.spans_by_id[resolved.entity_evidence_ids["e1"][0]]
    relation_span = resolved.spans_by_id[resolved.relation_evidence_ids["r1"][0]]

    assert acme_span.chunk_id == "chunk-000001"
    assert acme_span.quote == "Acme Corporation"
    assert acme_span.start_offset == 0
    assert acme_span.end_offset == len("Acme Corporation")
    assert acme_span.span_hash.startswith("sha256:")
    assert acme_span.stable_id.startswith("ev_")
    assert relation_span.start_offset == 0
    assert relation_span.end_offset == len(
        "Acme Corporation is headquartered in Berlin"
    )


def test_resolve_batch_evidence_rejects_absent_quote() -> None:
    batch = ExtractionBatch(
        input_chunk_ids=["chunk-000001"],
        entities=[
            ExtractedEntityProposal(
                local_id="e1",
                name="Acme Corporation",
                entity_type="organization",
                evidence=[EvidenceProposal(chunk_id="chunk-000001", quote="not present")],
            )
        ],
    )

    with pytest.raises(EvidenceResolutionError, match="quote was not found"):
        resolve_batch_evidence(
            batch,
            document_version_id=VERSION_ID,
            chunks=[
                ExtractionInputChunk(
                    chunk_id="chunk-000001",
                    text="Acme Corporation is headquartered in Berlin.",
                )
            ],
        )


def test_resolve_batch_evidence_rejects_repeated_quote_without_start_hint() -> None:
    batch = ExtractionBatch(
        input_chunk_ids=["chunk-000001"],
        entities=[
            ExtractedEntityProposal(
                local_id="e1",
                name="Acme Corporation",
                entity_type="organization",
                evidence=[
                    EvidenceProposal(chunk_id="chunk-000001", quote="Acme Corporation")
                ],
            )
        ],
    )

    with pytest.raises(EvidenceResolutionError, match="ambiguous repeated quote"):
        resolve_batch_evidence(
            batch,
            document_version_id=VERSION_ID,
            chunks=[
                ExtractionInputChunk(
                    chunk_id="chunk-000001",
                    text="Acme Corporation acquired Acme Corporation.",
                )
            ],
        )


def test_resolve_batch_evidence_accepts_repeated_quote_with_valid_start_hint() -> None:
    quote = "Acme Corporation"
    text = "Acme Corporation acquired Acme Corporation."
    second_start = text.rfind(quote)
    batch = ExtractionBatch(
        input_chunk_ids=["chunk-000001"],
        entities=[
            ExtractedEntityProposal(
                local_id="e1",
                name="Acme Corporation",
                entity_type="organization",
                evidence=[
                    EvidenceProposal(
                        chunk_id="chunk-000001",
                        quote=quote,
                        start_hint=second_start,
                    )
                ],
            )
        ],
    )

    resolved = resolve_batch_evidence(
        batch,
        chunks=[ExtractionInputChunk(chunk_id="chunk-000001", text=text)],
        document_version_id=VERSION_ID,
    )

    span = resolved.spans_by_id[resolved.entity_evidence_ids["e1"][0]]
    assert span.start_offset == second_start
    assert span.end_offset == second_start + len(quote)


def test_resolve_batch_evidence_rejects_start_hint_that_is_not_an_occurrence() -> None:
    batch = ExtractionBatch(
        input_chunk_ids=["chunk-000001"],
        entities=[
            ExtractedEntityProposal(
                local_id="e1",
                name="Acme Corporation",
                entity_type="organization",
                evidence=[
                    EvidenceProposal(
                        chunk_id="chunk-000001",
                        quote="Acme Corporation",
                        start_hint=5,
                    )
                ],
            )
        ],
    )

    with pytest.raises(EvidenceResolutionError, match="start_hint does not identify"):
        resolve_batch_evidence(
            batch,
            document_version_id=VERSION_ID,
            chunks=[
                ExtractionInputChunk(
                    chunk_id="chunk-000001",
                    text="Acme Corporation acquired Acme Corporation.",
                )
            ],
        )


def test_resolve_batch_evidence_rejects_chunk_scope_mismatch() -> None:
    batch = ExtractionBatch(
        input_chunk_ids=["chunk-000001", "chunk-000002"],
        entities=[
            ExtractedEntityProposal(
                local_id="e1",
                name="Acme Corporation",
                entity_type="organization",
                evidence=[
                    EvidenceProposal(chunk_id="chunk-000001", quote="Acme Corporation")
                ],
            )
        ],
    )

    with pytest.raises(EvidenceResolutionError, match="chunk scope mismatch"):
        resolve_batch_evidence(
            batch,
            document_version_id=VERSION_ID,
            chunks=[
                ExtractionInputChunk(
                    chunk_id="chunk-000001",
                    text="Acme Corporation is headquartered in Berlin.",
                )
            ],
        )
