from pathlib import PurePath

from flint_graph.application.parsing.errors import ParserUnsupportedFormatError
from flint_graph.application.parsing.models import SourceFormat, SourceMetadata

_TEXT_TYPES = {
    "text/plain": SourceFormat.TEXT,
    "text/markdown": SourceFormat.MARKDOWN,
    "text/x-markdown": SourceFormat.MARKDOWN,
    "text/html": SourceFormat.HTML,
    "application/xhtml+xml": SourceFormat.HTML,
    "application/pdf": SourceFormat.PDF,
}

_EXTENSIONS = {
    ".txt": SourceFormat.TEXT,
    ".text": SourceFormat.TEXT,
    ".md": SourceFormat.MARKDOWN,
    ".markdown": SourceFormat.MARKDOWN,
    ".html": SourceFormat.HTML,
    ".htm": SourceFormat.HTML,
    ".pdf": SourceFormat.PDF,
}


def detect_source_format(content: bytes, metadata: SourceMetadata) -> SourceFormat:
    if content.startswith(b"%PDF-"):
        return SourceFormat.PDF

    content_type = _base_content_type(metadata.content_type)
    if content_type in _TEXT_TYPES:
        return _TEXT_TYPES[content_type]

    if metadata.filename:
        suffix = PurePath(metadata.filename).suffix.lower()
        if suffix in _EXTENSIONS:
            return _EXTENSIONS[suffix]

    stripped = content.lstrip()[:64].lower()
    if stripped.startswith((b"<!doctype html", b"<html")):
        return SourceFormat.HTML

    if _looks_like_text(content):
        return SourceFormat.TEXT

    raise ParserUnsupportedFormatError("Source bytes do not match a supported parser format.")


def _base_content_type(content_type: str | None) -> str | None:
    if content_type is None:
        return None
    return content_type.split(";", 1)[0].strip().lower()


def _looks_like_text(content: bytes) -> bool:
    if not content:
        return True
    sample = content[:4096]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True
