from __future__ import annotations

from hashlib import sha256

from pydantic import BaseModel, ConfigDict

from atlas_rag.application.extraction_proposals import (
    EvidenceProposal,
    ExtractionBatch,
    ExtractionInputChunk,
)


class EvidenceResolutionError(ValueError):
    pass


class VerifiedEvidenceSpan(BaseModel):
    model_config = ConfigDict(frozen=True)

    stable_id: str
    chunk_id: str
    quote: str
    start_offset: int
    end_offset: int
    span_hash: str


class ResolvedBatchEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    spans_by_id: dict[str, VerifiedEvidenceSpan]
    entity_evidence_ids: dict[str, list[str]]
    relation_evidence_ids: dict[str, list[str]]
    claim_evidence_ids: dict[str, list[str]]


def resolve_batch_evidence(
    batch: ExtractionBatch, *, chunks: list[ExtractionInputChunk]
) -> ResolvedBatchEvidence:
    _validate_chunk_scope(batch, chunks)
    chunk_text_by_id = {chunk.chunk_id: chunk.text for chunk in chunks}
    spans_by_id: dict[str, VerifiedEvidenceSpan] = {}

    entity_evidence_ids: dict[str, list[str]] = {}
    for entity in batch.entities:
        entity_evidence_ids[entity.local_id] = _resolve_evidence_list(
            entity.evidence, chunk_text_by_id=chunk_text_by_id, spans_by_id=spans_by_id
        )

    relation_evidence_ids: dict[str, list[str]] = {}
    for relation in batch.relations:
        relation_evidence_ids[relation.local_id] = _resolve_evidence_list(
            relation.evidence, chunk_text_by_id=chunk_text_by_id, spans_by_id=spans_by_id
        )

    claim_evidence_ids: dict[str, list[str]] = {}
    for claim in batch.claims:
        claim_evidence_ids[claim.local_id] = _resolve_evidence_list(
            claim.evidence, chunk_text_by_id=chunk_text_by_id, spans_by_id=spans_by_id
        )

    return ResolvedBatchEvidence(
        spans_by_id=spans_by_id,
        entity_evidence_ids=entity_evidence_ids,
        relation_evidence_ids=relation_evidence_ids,
        claim_evidence_ids=claim_evidence_ids,
    )


def _validate_chunk_scope(batch: ExtractionBatch, chunks: list[ExtractionInputChunk]) -> None:
    batch_chunk_ids = set(batch.input_chunk_ids)
    provided_chunk_ids = {chunk.chunk_id for chunk in chunks}
    if batch_chunk_ids != provided_chunk_ids:
        raise EvidenceResolutionError("chunk scope mismatch for extraction batch")


def _resolve_evidence_list(
    evidence_items: list[EvidenceProposal],
    *,
    chunk_text_by_id: dict[str, str],
    spans_by_id: dict[str, VerifiedEvidenceSpan],
) -> list[str]:
    evidence_ids: list[str] = []
    for evidence in evidence_items:
        span = _resolve_one(evidence, chunk_text_by_id=chunk_text_by_id)
        spans_by_id.setdefault(span.stable_id, span)
        evidence_ids.append(span.stable_id)
    return evidence_ids


def _resolve_one(
    evidence: EvidenceProposal, *, chunk_text_by_id: dict[str, str]
) -> VerifiedEvidenceSpan:
    chunk_text = chunk_text_by_id.get(evidence.chunk_id)
    if chunk_text is None:
        raise EvidenceResolutionError(
            f"evidence chunk '{evidence.chunk_id}' was not provided"
        )

    occurrences = _find_occurrences(chunk_text, evidence.quote)
    if not occurrences:
        raise EvidenceResolutionError("evidence quote was not found in chunk text")
    if len(occurrences) == 1:
        start_offset = occurrences[0]
    elif evidence.start_hint is None:
        raise EvidenceResolutionError("ambiguous repeated quote requires start_hint")
    elif evidence.start_hint not in occurrences:
        raise EvidenceResolutionError("start_hint does not identify a quote occurrence")
    else:
        start_offset = evidence.start_hint
    end_offset = start_offset + len(evidence.quote)
    span_hash = _content_hash(evidence.quote.encode("utf-8"))
    stable_id = _stable_evidence_id(
        chunk_id=evidence.chunk_id,
        start_offset=start_offset,
        end_offset=end_offset,
        span_hash=span_hash,
    )
    return VerifiedEvidenceSpan(
        stable_id=stable_id,
        chunk_id=evidence.chunk_id,
        quote=evidence.quote,
        start_offset=start_offset,
        end_offset=end_offset,
        span_hash=span_hash,
    )


def _stable_evidence_id(
    *, chunk_id: str, start_offset: int, end_offset: int, span_hash: str
) -> str:
    digest = sha256(f"{chunk_id}:{start_offset}:{end_offset}:{span_hash}".encode()).hexdigest()
    return f"ev_{digest}"


def _content_hash(data: bytes) -> str:
    return "sha256:" + sha256(data).hexdigest()


def _find_occurrences(text: str, quote: str) -> list[int]:
    occurrences: list[int] = []
    start = 0
    while True:
        index = text.find(quote, start)
        if index < 0:
            return occurrences
        occurrences.append(index)
        start = index + 1
