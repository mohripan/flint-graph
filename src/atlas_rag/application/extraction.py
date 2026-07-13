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
    summary: str | None = None
    topics: list[str] = Field(default_factory=list)
    entities: list[ExtractedEntity] = Field(default_factory=list)
    claims: list[ExtractedClaim] = Field(default_factory=list)


def parse_extraction_response(response_text: str) -> ExtractedDocumentFacts:
    """Parse an LLM extraction response resiliently.

    Only a non-JSON or non-object response is a hard failure. Otherwise valid
    entities and claims are kept and malformed items (e.g. a null predicate, a
    list-valued object, a missing field) are dropped, so a small local model that
    emits mostly-correct output still yields usable graph facts. ``summary`` is
    optional because entities and claims are the primary product of the pipeline.
    """

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise ExtractionValidationError("LLM response must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ExtractionValidationError("LLM response must be a JSON object.")

    return ExtractedDocumentFacts(
        title=_optional_str(payload.get("title")),
        summary=_optional_str(payload.get("summary")),
        topics=_string_list(payload.get("topics")),
        entities=_valid_items(payload.get("entities"), ExtractedEntity),
        claims=_valid_items(payload.get("claims"), ExtractedClaim),
    )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _valid_items[ModelT: BaseModel](value: object, model: type[ModelT]) -> list[ModelT]:
    if not isinstance(value, list):
        return []
    items: list[ModelT] = []
    for raw in value:
        try:
            items.append(model.model_validate(raw))
        except ValidationError:
            continue
    return items


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
            "Rules:",
            "- summary is a short non-empty string describing the document.",
            "- Each entity has a non-empty name and a type from: "
            "person, organization, place, concept, other.",
            "- Each claim is a (subject, predicate, object) triple.",
            "- subject, predicate, and object must each be a single non-empty string; "
            "never use null or a list.",
            "- evidence_chunk_ids is a list of the bracketed chunk ids that support the claim.",
            "Return only JSON matching this schema:",
            json.dumps(schema, indent=2, sort_keys=True),
            "Document chunks:",
            chunk_text,
        ]
    )
