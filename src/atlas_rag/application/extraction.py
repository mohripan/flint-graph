from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

EXTRACTION_SCHEMA_VERSION = "2"
EXTRACTION_PROMPT_VERSION = "builtin-graph-v2"


class ExtractionValidationError(ValueError):
    pass


class ExtractedEntity(BaseModel):
    name: str = Field(min_length=1)
    type: Literal["person", "organization", "place", "concept", "other"]


class ExtractedClaim(BaseModel):
    subject: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object: str = Field(min_length=1)
    evidence_chunk_ids: list[str] = Field(default_factory=list)


class ExtractedDocumentFacts(BaseModel):
    title: str | None = None
    summary: str = Field(min_length=1)
    topics: list[str] = Field(default_factory=list)
    entities: list[ExtractedEntity] = Field(default_factory=list)
    claims: list[ExtractedClaim] = Field(default_factory=list)


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
        "claims": [
            {
                "subject": "string",
                "predicate": "string",
                "object": "string",
                "evidence_chunk_ids": ["string"],
            }
        ],
    }
    chunk_text = "\n\n".join(f"[{chunk_id}]\n{text}" for chunk_id, text in chunks)
    return "\n".join(
        [
            "Extract structured facts and relationship claims from the document chunks.",
            "Each claim is a (subject, predicate, object) triple stating a relationship "
            "between entities named in the document.",
            "Populate evidence_chunk_ids with the chunk ids that support each claim.",
            "Return only JSON matching this schema:",
            json.dumps(schema, indent=2, sort_keys=True),
            "Document chunks:",
            chunk_text,
        ]
    )
