from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from re import DOTALL, Match, finditer
from typing import Literal, Protocol, cast

from pypdf import PdfReader

from flint_graph.application.parsing.detection import detect_source_format
from flint_graph.application.parsing.errors import ParserDecodeError
from flint_graph.application.parsing.models import (
    NormalizedDocument,
    NormalizedElement,
    SourceFormat,
    SourceMetadata,
    SourceOffsets,
    SourceReference,
)


class SourceParser(Protocol):
    def parse(self, content: bytes, metadata: SourceMetadata) -> NormalizedDocument: ...


def parse_normalized_document(
    content: bytes,
    *,
    metadata: SourceMetadata,
) -> NormalizedDocument:
    source_format = detect_source_format(content, metadata)
    parser = _PARSERS[source_format]
    return parser.parse(content, metadata)


class TextParser:
    def parse(self, content: bytes, metadata: SourceMetadata) -> NormalizedDocument:
        text = _decode_text(content)
        elements = [
            _element(
                index=index,
                element_type="paragraph",
                text=match.group(0).strip(),
                source_offsets=SourceOffsets(
                    start=match.start(), end=match.start() + len(match.group(0).rstrip()),
                ),
            )
            for index, match in enumerate(_paragraph_matches(text), start=1)
            if match.group(0).strip()
        ]
        return _document(metadata, SourceFormat.TEXT, elements)


class MarkdownParser:
    def parse(self, content: bytes, metadata: SourceMetadata) -> NormalizedDocument:
        text = _decode_text(content)
        elements: list[NormalizedElement] = []
        title: str | None = None
        lines = text.splitlines()
        in_code_block = False
        code_lines: list[str] = []
        code_start = 0
        paragraph_lines: list[str] = []
        paragraph_start = 0

        def flush_paragraph(end_offset: int) -> None:
            nonlocal paragraph_lines, paragraph_start
            paragraph = " ".join(line.strip() for line in paragraph_lines).strip()
            if paragraph:
                elements.append(
                    _element(
                        index=len(elements) + 1,
                        element_type="paragraph",
                        text=paragraph,
                        source_offsets=SourceOffsets(start=paragraph_start, end=end_offset),
                    )
                )
            paragraph_lines = []

        offset = 0
        for line in lines:
            stripped = line.strip()
            line_start = offset
            line_end = offset + len(line)
            offset = line_end + 1

            if stripped.startswith("```"):
                if in_code_block:
                    elements.append(
                        _element(
                            index=len(elements) + 1,
                            element_type="code_block",
                            text="\n".join(code_lines).strip("\n"),
                            source_offsets=SourceOffsets(start=code_start, end=line_end),
                        )
                    )
                    code_lines = []
                    in_code_block = False
                else:
                    flush_paragraph(line_start)
                    code_start = offset
                    in_code_block = True
                continue

            if in_code_block:
                code_lines.append(line)
                continue

            if not stripped:
                flush_paragraph(line_start)
                continue

            heading = _heading(stripped)
            if heading is not None:
                flush_paragraph(line_start)
                level, heading_text = heading
                if title is None and level == 1:
                    title = heading_text
                elements.append(
                    _element(
                        index=len(elements) + 1,
                        element_type="heading",
                        text=heading_text,
                        level=level,
                        source_offsets=SourceOffsets(start=line_start, end=line_end),
                    )
                )
                continue

            list_item = _list_item(stripped)
            if list_item is not None:
                flush_paragraph(line_start)
                elements.append(
                    _element(
                        index=len(elements) + 1,
                        element_type="list_item",
                        text=list_item,
                        source_offsets=SourceOffsets(start=line_start, end=line_end),
                    )
                )
                continue

            if not paragraph_lines:
                paragraph_start = line_start
            paragraph_lines.append(line)

        flush_paragraph(len(text))
        return _document(metadata, SourceFormat.MARKDOWN, elements, title=title)


class HTMLDocumentParser:
    def parse(self, content: bytes, metadata: SourceMetadata) -> NormalizedDocument:
        text = _decode_text(content)
        collector = _HTMLCollector()
        collector.feed(text)
        return _document(
            metadata,
            SourceFormat.HTML,
            [
                _element(
                    index=index,
                    element_type=tag.element_type,
                    text=tag.text,
                    level=tag.level,
                )
                for index, tag in enumerate(collector.elements, start=1)
            ],
            title=collector.title,
        )


class PDFParser:
    def parse(self, content: bytes, metadata: SourceMetadata) -> NormalizedDocument:
        try:
            reader = PdfReader(BytesIO(content))
            elements: list[NormalizedElement] = []
            for page_number, page in enumerate(reader.pages, start=1):
                page_text = (page.extract_text() or "").strip()
                if not page_text:
                    continue
                for paragraph in _split_paragraphs(page_text):
                    elements.append(
                        _element(
                            index=len(elements) + 1,
                            element_type="paragraph",
                            text=paragraph,
                            page=page_number,
                        )
                    )
        except Exception as exc:
            raise ParserDecodeError("PDF source could not be parsed.") from exc

        if not elements:
            raise ParserDecodeError("PDF did not contain extractable text.")
        return _document(metadata, SourceFormat.PDF, elements)


@dataclass(slots=True)
class _CollectedElement:
    element_type: str
    text: str
    level: int | None = None


class _HTMLCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.elements: list[_CollectedElement] = []
        self._stack: list[str] = []
        self._buffer: list[str] = []
        self._current_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"title", "p", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._flush()
            self._current_tag = tag
            self._buffer = []
        self._stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == self._current_tag:
            self._flush()
        if tag in self._stack:
            self._stack.remove(tag)

    def handle_data(self, data: str) -> None:
        if self._current_tag is not None:
            self._buffer.append(data)

    def _flush(self) -> None:
        if self._current_tag is None:
            return
        text = " ".join(" ".join(self._buffer).split())
        tag = self._current_tag
        self._current_tag = None
        self._buffer = []
        if not text:
            return
        if tag == "title":
            self.title = text
        elif tag.startswith("h"):
            self.elements.append(_CollectedElement("heading", text, int(tag[1])))
        elif tag == "li":
            self.elements.append(_CollectedElement("list_item", text))
        elif tag == "p":
            self.elements.append(_CollectedElement("paragraph", text))


_PARSERS: dict[SourceFormat, SourceParser] = {
    SourceFormat.TEXT: TextParser(),
    SourceFormat.MARKDOWN: MarkdownParser(),
    SourceFormat.HTML: HTMLDocumentParser(),
    SourceFormat.PDF: PDFParser(),
}


def _document(
    metadata: SourceMetadata,
    source_format: SourceFormat,
    elements: list[NormalizedElement],
    *,
    title: str | None = None,
    warnings: list[str] | None = None,
) -> NormalizedDocument:
    return NormalizedDocument(
        source=SourceReference(
            document_id=metadata.document_id,
            document_version_id=metadata.document_version_id,
            content_hash=metadata.content_hash,
        ),
        format=source_format,
        title=title,
        elements=elements,
        warnings=warnings or [],
    )


def _element(
    *,
    index: int,
    element_type: str,
    text: str,
    level: int | None = None,
    page: int | None = None,
    source_offsets: SourceOffsets | None = None,
) -> NormalizedElement:
    return NormalizedElement(
        id=f"element-{index:06d}",
        type=cast(Literal["heading", "paragraph", "list_item", "code_block"], element_type),
        text=text,
        level=level,
        page=page,
        source_offsets=source_offsets,
    )


def _decode_text(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParserDecodeError("Text source must be valid UTF-8.") from exc


def _paragraph_matches(text: str) -> list[Match[str]]:
    return list(finditer(r"\S.*?(?=\n[^\S\n]*\n|\Z)", text, flags=DOTALL))


def _split_paragraphs(text: str) -> list[str]:
    return [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]


def _heading(line: str) -> tuple[int, str] | None:
    stripped = line.lstrip()
    marker = len(stripped) - len(stripped.lstrip("#"))
    if marker < 1 or marker > 6 or not stripped[marker:].startswith(" "):
        return None
    return marker, stripped[marker:].strip()


def _list_item(line: str) -> str | None:
    stripped = line.lstrip()
    for prefix in ("- ", "* ", "+ "):
        if stripped.startswith(prefix):
            return stripped[2:].strip()
    return None
