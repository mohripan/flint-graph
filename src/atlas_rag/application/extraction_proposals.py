from __future__ import annotations

import re
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROPOSAL_SCHEMA_VERSION: Literal["1"] = "1"

EntityTypeName = Literal["person", "organization", "place", "concept", "other"]

_PREDICATE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
_CAPITALIZED_PHRASE_RE = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*)*")


class ExtractionInputChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1)


class ExtractionBatchRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1"] = PROPOSAL_SCHEMA_VERSION
    chunks: list[ExtractionInputChunk] = Field(min_length=1, max_length=100)


class StructuredExtractionModel(Protocol):
    async def extract_batch(self, request: ExtractionBatchRequest) -> ExtractionBatch: ...


class EvidenceProposal(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str = Field(min_length=1, max_length=100)
    quote: str = Field(min_length=1, max_length=4000)
    start_hint: int | None = Field(default=None, ge=0)


class ExtractedEntityProposal(BaseModel):
    model_config = ConfigDict(frozen=True)

    local_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=500)
    entity_type: EntityTypeName
    aliases: list[str] = Field(default_factory=list, max_length=20)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    attributes: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceProposal] = Field(min_length=1, max_length=20)


class ExtractedRelationProposal(BaseModel):
    model_config = ConfigDict(frozen=True)

    local_id: str = Field(min_length=1, max_length=100)
    subject_entity_id: str = Field(min_length=1, max_length=100)
    predicate: str = Field(min_length=1, max_length=200)
    object_entity_id: str = Field(min_length=1, max_length=100)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence: list[EvidenceProposal] = Field(min_length=1, max_length=20)

    @field_validator("predicate")
    @classmethod
    def _validate_predicate(cls, value: str) -> str:
        if _PREDICATE_RE.fullmatch(value) is None:
            raise ValueError("malformed predicate")
        return value

    @model_validator(mode="after")
    def _reject_self_reference(self) -> ExtractedRelationProposal:
        if self.subject_entity_id == self.object_entity_id:
            raise ValueError("self-referential relation")
        return self


class ExtractedClaimProposal(BaseModel):
    model_config = ConfigDict(frozen=True)

    local_id: str = Field(min_length=1, max_length=100)
    subject_entity_id: str | None = Field(default=None, min_length=1, max_length=100)
    predicate: str = Field(min_length=1, max_length=200)
    object_entity_id: str | None = Field(default=None, min_length=1, max_length=100)
    object_text: str | None = Field(default=None, min_length=1, max_length=1000)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence: list[EvidenceProposal] = Field(min_length=1, max_length=20)

    @field_validator("predicate")
    @classmethod
    def _validate_predicate(cls, value: str) -> str:
        if _PREDICATE_RE.fullmatch(value) is None:
            raise ValueError("malformed predicate")
        return value

    @model_validator(mode="after")
    def _validate_object_form(self) -> ExtractedClaimProposal:
        object_forms = [self.object_entity_id is not None, self.object_text is not None]
        if sum(object_forms) != 1:
            raise ValueError("claim must include exactly one object form")
        return self


class ExtractionBatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1"] = PROPOSAL_SCHEMA_VERSION
    input_chunk_ids: list[str] = Field(min_length=1, max_length=100)
    entities: list[ExtractedEntityProposal] = Field(default_factory=list, max_length=200)
    relations: list[ExtractedRelationProposal] = Field(default_factory=list, max_length=200)
    claims: list[ExtractedClaimProposal] = Field(default_factory=list, max_length=400)

    @model_validator(mode="after")
    def _validate_batch_integrity(self) -> ExtractionBatch:
        self._validate_unique_local_ids()
        self._validate_references()
        self._validate_evidence_scope()
        return self

    def _validate_unique_local_ids(self) -> None:
        seen: set[str] = set()
        for local_id in [
            *(entity.local_id for entity in self.entities),
            *(relation.local_id for relation in self.relations),
            *(claim.local_id for claim in self.claims),
        ]:
            if local_id in seen:
                raise ValueError(f"duplicate local id '{local_id}'")
            seen.add(local_id)

    def _validate_references(self) -> None:
        entity_ids = {entity.local_id for entity in self.entities}
        for relation in self.relations:
            if (
                relation.subject_entity_id not in entity_ids
                or relation.object_entity_id not in entity_ids
            ):
                raise ValueError("unknown entity reference")
        for claim in self.claims:
            if claim.subject_entity_id is not None and claim.subject_entity_id not in entity_ids:
                raise ValueError("unknown entity reference")
            if claim.object_entity_id is not None and claim.object_entity_id not in entity_ids:
                raise ValueError("unknown entity reference")

    def _validate_evidence_scope(self) -> None:
        chunk_ids = set(self.input_chunk_ids)
        for evidence in self._all_evidence():
            if evidence.chunk_id not in chunk_ids:
                raise ValueError("evidence chunk is outside invocation input")

    def _all_evidence(self) -> list[EvidenceProposal]:
        return [
            *(
                evidence
                for entity in self.entities
                for evidence in entity.evidence
            ),
            *(
                evidence
                for relation in self.relations
                for evidence in relation.evidence
            ),
            *(evidence for claim in self.claims for evidence in claim.evidence),
        ]


class DeterministicExtractionModel:
    async def extract_batch(self, request: ExtractionBatchRequest) -> ExtractionBatch:
        entities_by_key: dict[str, ExtractedEntityProposal] = {}
        evidence_by_key: dict[str, list[EvidenceProposal]] = {}
        ordered_keys: list[str] = []

        for chunk in request.chunks:
            for match in _CAPITALIZED_PHRASE_RE.finditer(chunk.text):
                surface = match.group(0).strip()
                if not surface:
                    continue
                key = _normalize_surface(surface)
                if key not in entities_by_key:
                    ordered_keys.append(key)
                    local_id = f"e{len(ordered_keys)}"
                    entities_by_key[key] = ExtractedEntityProposal(
                        local_id=local_id,
                        name=surface,
                        entity_type="other",
                        evidence=[EvidenceProposal(chunk_id=chunk.chunk_id, quote=surface)],
                    )
                    evidence_by_key[key] = list(entities_by_key[key].evidence)
                else:
                    evidence_by_key[key].append(
                        EvidenceProposal(chunk_id=chunk.chunk_id, quote=surface)
                    )

        entities = [
            entities_by_key[key].model_copy(update={"evidence": evidence_by_key[key]})
            for key in ordered_keys
        ]
        return ExtractionBatch(
            input_chunk_ids=[chunk.chunk_id for chunk in request.chunks],
            entities=entities,
        )


def _normalize_surface(surface: str) -> str:
    return " ".join(surface.casefold().split())
