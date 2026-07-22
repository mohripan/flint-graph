from uuid import UUID

from flint_graph.application.chunking import ChunkingConfig, chunk_normalized_document
from flint_graph.application.parsing import (
    NormalizedDocument,
    NormalizedElement,
    SourceFormat,
    SourceReference,
)

DOCUMENT_ID = UUID("11111111-1111-4111-8111-111111111111")
VERSION_ID = UUID("22222222-2222-4222-8222-222222222222")
CONTENT_HASH = "sha256:" + "b" * 64


def _document(elements: list[NormalizedElement]) -> NormalizedDocument:
    return NormalizedDocument(
        source=SourceReference(
            document_id=DOCUMENT_ID,
            document_version_id=VERSION_ID,
            content_hash=CONTENT_HASH,
        ),
        format=SourceFormat.MARKDOWN,
        title="Acme",
        elements=elements,
    )


def test_chunker_preserves_heading_context_and_structural_boundaries() -> None:
    artifact = _document(
        [
            NormalizedElement(id="element-000001", type="heading", text="Acme", level=1),
            NormalizedElement(id="element-000002", type="paragraph", text="First paragraph."),
            NormalizedElement(id="element-000003", type="heading", text="Details", level=2),
            NormalizedElement(id="element-000004", type="list_item", text="First bullet"),
            NormalizedElement(id="element-000005", type="code_block", text="print('stable')"),
        ]
    )

    manifest = chunk_normalized_document(
        artifact,
        config=ChunkingConfig(max_chunk_chars=80, overlap_chars=12),
    )

    assert manifest.schema_version == "1"
    assert manifest.chunking_config == {
        "max_chunk_chars": 80,
        "overlap_chars": 12,
    }
    chunk_summaries = [
        (chunk.text, chunk.heading_path, chunk.source_element_ids)
        for chunk in manifest.chunks
    ]
    assert chunk_summaries == [
        ("First paragraph.", ["Acme"], ["element-000002"]),
        (
            "First bullet\n\nprint('stable')",
            ["Acme", "Details"],
            ["element-000004", "element-000005"],
        ),
    ]


def test_chunker_splits_oversized_elements_with_bounded_overlap() -> None:
    artifact = _document(
        [
            NormalizedElement(id="element-000001", type="heading", text="Large", level=1),
            NormalizedElement(
                id="element-000002",
                type="paragraph",
                text="abcdefghijklmnopqrstuvwxyz",
            ),
        ]
    )

    manifest = chunk_normalized_document(
        artifact,
        config=ChunkingConfig(max_chunk_chars=10, overlap_chars=3),
    )

    assert [chunk.text for chunk in manifest.chunks] == [
        "abcdefghij",
        "hijklmnopq",
        "opqrstuvwx",
        "vwxyz",
    ]
    assert all(chunk.heading_path == ["Large"] for chunk in manifest.chunks)
    assert all(chunk.source_element_ids == ["element-000002"] for chunk in manifest.chunks)


def test_chunker_is_deterministic_for_same_artifact_and_config() -> None:
    artifact = _document(
        [
            NormalizedElement(id="element-000001", type="heading", text="Stable", level=1),
            NormalizedElement(id="element-000002", type="paragraph", text="Same input."),
        ]
    )
    config = ChunkingConfig(max_chunk_chars=60, overlap_chars=8)

    first = chunk_normalized_document(artifact, config=config)
    second = chunk_normalized_document(artifact, config=config)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.chunks[0].chunk_hash.startswith("sha256:")
