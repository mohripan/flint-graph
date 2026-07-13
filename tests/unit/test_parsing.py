import base64
from uuid import UUID

import pytest
from pydantic import ValidationError

from atlas_rag.application.parsing import (
    BoundedParserRunner,
    NormalizedDocument,
    NormalizedElement,
    ParserLimitError,
    ParserLimits,
    ParserUnsupportedFormatError,
    SourceFormat,
    SourceMetadata,
    detect_source_format,
)
from atlas_rag.application.parsing.parsers import parse_normalized_document

DOCUMENT_ID = UUID("11111111-1111-4111-8111-111111111111")
VERSION_ID = UUID("22222222-2222-4222-8222-222222222222")
CONTENT_HASH = "sha256:" + "a" * 64


def _source_metadata(
    *,
    content_type: str | None = None,
    filename: str | None = None,
) -> SourceMetadata:
    return SourceMetadata(
        document_id=DOCUMENT_ID,
        document_version_id=VERSION_ID,
        content_hash=CONTENT_HASH,
        content_type=content_type,
        filename=filename,
    )


def _text_pdf_bytes() -> bytes:
    return base64.b64decode(
        b"JVBERi0xLjQKMSAwIG9iago8PCAvVHlwZSAvQ2F0YWxvZyAvUGFnZXMgMiAwIFIgPj4KZW5kb2JqCjIg"
        b"MCBvYmoKPDwgL1R5cGUgL1BhZ2VzIC9LaWRzIFszIDAgUl0gL0NvdW50IDEgPj4KZW5kb2JqCjMgMCBv"
        b"YmoKPDwgL1R5cGUgL1BhZ2UgL1BhcmVudCAyIDAgUiAvTWVkaWFCb3ggWzAgMCAzMDAgMTQ0XSAvUmVz"
        b"b3VyY2VzIDw8IC9Gb250IDw8IC9GMSA0IDAgUiA+PiA+PiAvQ29udGVudHMgNSAwIFIgPj4KZW5kb2Jq"
        b"CjQgMCBvYmoKPDwgL1R5cGUgL0ZvbnQgL1N1YnR5cGUgL1R5cGUxIC9CYXNlRm9udCAvSGVsdmV0aWNh"
        b"ID4+CmVuZG9iago1IDAgb2JqCjw8IC9MZW5ndGggNDQgPj4Kc3RyZWFtCkJUCi9GMSAyNCBUZgo1MCAx"
        b"MDAgVGQKKEF0bGFzIFBERiB0ZXh0KSBUagpFVAplbmRzdHJlYW0KZW5kb2JqCnhyZWYKMCA2CjAwMDAw"
        b"MDAwMDAgNjU1MzUgZiAKMDAwMDAwMDAwOSAwMDAwMCBuIAowMDAwMDAwMDU4IDAwMDAwIG4gCjAwMDAw"
        b"MDAxMTUgMDAwMDAgbiAKMDAwMDAwMDI2MCAwMDAwMCBuIAowMDAwMDAwMzMwIDAwMDAwIG4gCnRyYWls"
        b"ZXIKPDwgL1NpemUgNiAvUm9vdCAxIDAgUiA+PgpzdGFydHhyZWYKNDIzCiUlRU9GCg=="
    )


@pytest.mark.parametrize(
    ("content", "metadata", "expected"),
    [
        (
            b"%PDF-1.4\n",
            _source_metadata(content_type="application/octet-stream"),
            SourceFormat.PDF,
        ),
        (
            b"<html><body>Hi</body></html>",
            _source_metadata(filename="page.html"),
            SourceFormat.HTML,
        ),
        (b"# Heading\n", _source_metadata(content_type="text/markdown"), SourceFormat.MARKDOWN),
        (b"plain text", _source_metadata(content_type="text/plain"), SourceFormat.TEXT),
    ],
)
def test_detect_source_format(
    content: bytes,
    metadata: SourceMetadata,
    expected: SourceFormat,
) -> None:
    assert detect_source_format(content, metadata) == expected


def test_detect_source_format_rejects_unknown_binary() -> None:
    with pytest.raises(ParserUnsupportedFormatError):
        detect_source_format(b"\x00\x01\x02\x03", _source_metadata(filename="blob.bin"))


def test_normalized_artifact_requires_non_empty_text() -> None:
    with pytest.raises(ValidationError):
        NormalizedDocument(
            source={
                "document_id": DOCUMENT_ID,
                "document_version_id": VERSION_ID,
                "content_hash": CONTENT_HASH,
            },
            format=SourceFormat.TEXT,
            elements=[NormalizedElement(id="element-000001", type="paragraph", text="")],
        )


def test_parse_plain_text_into_paragraph_elements() -> None:
    artifact = parse_normalized_document(
        b"First paragraph.\n\nSecond paragraph.",
        metadata=_source_metadata(content_type="text/plain"),
    )

    assert artifact.schema_version == "1"
    assert artifact.format == SourceFormat.TEXT
    assert [element.model_dump(exclude_none=True) for element in artifact.elements] == [
        {
            "id": "element-000001",
            "type": "paragraph",
            "text": "First paragraph.",
            "source_offsets": {"start": 0, "end": 16},
        },
        {
            "id": "element-000002",
            "type": "paragraph",
            "text": "Second paragraph.",
            "source_offsets": {"start": 18, "end": 35},
        },
    ]


def test_parse_markdown_preserves_headings_lists_and_code_blocks() -> None:
    artifact = parse_normalized_document(
        b"# Title\n\nIntro text.\n\n- one\n- two\n\n```python\nprint('hi')\n```",
        metadata=_source_metadata(content_type="text/markdown"),
    )

    assert artifact.title == "Title"
    assert [(element.type, element.text, element.level) for element in artifact.elements] == [
        ("heading", "Title", 1),
        ("paragraph", "Intro text.", None),
        ("list_item", "one", None),
        ("list_item", "two", None),
        ("code_block", "print('hi')", None),
    ]


def test_parse_html_extracts_title_headings_paragraphs_and_list_items() -> None:
    artifact = parse_normalized_document(
        b"<html><head><title>Page Title</title></head><body>"
        b"<h1>Main</h1><p>Body text.</p><ul><li>First</li></ul></body></html>",
        metadata=_source_metadata(content_type="text/html"),
    )

    assert artifact.title == "Page Title"
    assert [(element.type, element.text, element.level) for element in artifact.elements] == [
        ("heading", "Main", 1),
        ("paragraph", "Body text.", None),
        ("list_item", "First", None),
    ]


def test_parse_text_based_pdf_extracts_page_text() -> None:
    artifact = parse_normalized_document(
        _text_pdf_bytes(),
        metadata=_source_metadata(content_type="application/pdf"),
    )

    assert artifact.format == SourceFormat.PDF
    assert [(element.type, element.text, element.page) for element in artifact.elements] == [
        ("paragraph", "Atlas PDF text", 1)
    ]


def test_subprocess_runner_returns_normalized_artifact() -> None:
    runner = BoundedParserRunner(
        limits=ParserLimits(
            timeout_seconds=10,
            max_raw_bytes=1024,
            max_normalized_bytes=10_000,
            max_elements=10,
        )
    )

    artifact = runner.parse(
        b"Subprocess paragraph.",
        metadata=_source_metadata(content_type="text/plain"),
    )

    assert artifact.format == SourceFormat.TEXT
    assert artifact.elements[0].text == "Subprocess paragraph."


def test_subprocess_runner_enforces_raw_byte_limit() -> None:
    runner = BoundedParserRunner(
        limits=ParserLimits(
            timeout_seconds=10,
            max_raw_bytes=4,
            max_normalized_bytes=10_000,
            max_elements=10,
        )
    )

    with pytest.raises(ParserLimitError):
        runner.parse(b"too large", metadata=_source_metadata(content_type="text/plain"))


def test_subprocess_runner_enforces_element_limit() -> None:
    runner = BoundedParserRunner(
        limits=ParserLimits(
            timeout_seconds=10,
            max_raw_bytes=1024,
            max_normalized_bytes=10_000,
            max_elements=1,
        )
    )

    with pytest.raises(ParserLimitError):
        runner.parse(b"one\n\ntwo", metadata=_source_metadata(content_type="text/plain"))
