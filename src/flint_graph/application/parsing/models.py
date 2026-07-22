from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class SourceFormat(StrEnum):
    TEXT = "text"
    MARKDOWN = "markdown"
    HTML = "html"
    PDF = "pdf"


class SourceMetadata(BaseModel):
    document_id: UUID
    document_version_id: UUID
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    content_type: str | None = None
    filename: str | None = None


class SourceReference(BaseModel):
    document_id: UUID
    document_version_id: UUID
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class SourceOffsets(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @field_validator("end")
    @classmethod
    def end_must_not_precede_start(cls, value: int, info: object) -> int:
        data = getattr(info, "data", {})
        start = data.get("start")
        if isinstance(start, int) and value < start:
            raise ValueError("end must be greater than or equal to start")
        return value


class NormalizedElement(BaseModel):
    id: str = Field(pattern=r"^element-[0-9]{6}$")
    type: Literal["heading", "paragraph", "list_item", "code_block"]
    text: str = Field(min_length=1)
    level: int | None = Field(default=None, ge=1, le=6)
    page: int | None = Field(default=None, ge=1)
    source_offsets: SourceOffsets | None = None


class NormalizedDocument(BaseModel):
    schema_version: Literal["1"] = "1"
    source: SourceReference
    format: SourceFormat
    title: str | None = None
    elements: list[NormalizedElement] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class ParserLimits(BaseModel):
    timeout_seconds: float = Field(gt=0.0)
    max_raw_bytes: int = Field(ge=1)
    max_normalized_bytes: int = Field(ge=1)
    max_elements: int = Field(ge=1)
