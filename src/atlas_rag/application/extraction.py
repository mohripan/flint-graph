from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

EXTRACTION_SCHEMA_VERSION = "1"
EXTRACTION_PROMPT_VERSION = "builtin-summary-v1"


class ExtractionValidationError(ValueError):
    pass


class ExtractedEntity(BaseModel):
    name: str = Field(min_length=1)
    type: Literal["person", "organization", "place", "concept", "other"]


class ExtractedDocumentFacts(BaseModel):
    title: str | None = None
    summary: str = Field(min_length=1)
    topics: list[str] = Field(default_factory=list)
    entities: list[ExtractedEntity] = Field(default_factory=list)


def parse_extraction_response(response_text: str) -> ExtractedDocumentFacts:
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise ExtractionValidationError("LLM response must be valid JSON.") from exc

    try:
        return ExtractedDocumentFacts.model_validate(payload)
    except ValidationError as exc:
        raise ExtractionValidationError(
            f"LLM response does not match extraction schema: {exc}"
        ) from exc


def build_extraction_prompt(chunks: Sequence[tuple[str, str]]) -> str:
    schema = {
        "title": "string|null",
        "summary": "string",
        "topics": ["string"],
        "entities": [
            {
                "name": "string",
                "type": "person|organization|place|concept|other",
            }
        ],
    }
    chunk_text = "\n\n".join(f"[{chunk_id}]\n{text}" for chunk_id, text in chunks)
    return "\n".join(
        [
            "Extract structured facts from the document chunks.",
            "Return only JSON matching this schema:",
            json.dumps(schema, indent=2, sort_keys=True),
            "Document chunks:",
            chunk_text,
        ]
    )
