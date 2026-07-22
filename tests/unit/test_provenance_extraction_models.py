from sqlalchemy import UniqueConstraint

from flint_graph.infrastructure.db.base import Base
from flint_graph.infrastructure.db.models import (
    EntityResolutionCandidate,
    EvidenceSpan,
    ExtractedEntity,
    ExtractionRun,
)


def _unique_column_sets(model: type) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in model.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_all_provenance_extraction_tables_are_registered() -> None:
    tables = set(Base.metadata.tables)
    expected = {
        "extraction_runs",
        "extraction_invocations",
        "extraction_artifacts",
        "evidence_spans",
        "extracted_entities",
        "extracted_relations",
        "extracted_claims",
        "extracted_entity_evidence",
        "extracted_relation_evidence",
        "extracted_claim_evidence",
        "entity_resolution_candidates",
    }
    assert expected <= tables


def test_extraction_run_is_unique_per_document_version_and_ready_run_key() -> None:
    assert (
        "document_version_id",
        "input_hash",
        "schema_version",
        "prompt_version",
        "extractor_version",
        "model_name",
    ) in _unique_column_sets(ExtractionRun)


def test_evidence_span_is_unique_per_stable_id_and_per_location() -> None:
    unique_sets = _unique_column_sets(EvidenceSpan)

    assert ("tenant_id", "stable_id") in unique_sets
    assert (
        "tenant_id",
        "document_version_id",
        "chunk_id",
        "start_offset",
        "end_offset",
        "span_hash",
    ) in unique_sets


def test_extracted_entity_stable_id_is_unique_per_tenant() -> None:
    assert ("tenant_id", "stable_id") in _unique_column_sets(ExtractedEntity)


def test_entity_resolution_candidate_links_source_extracted_entity() -> None:
    foreign_keys = {
        (fk.parent.name, fk.column.table.name, fk.column.name)
        for fk in EntityResolutionCandidate.__table__.foreign_keys
    }

    assert ("source_extracted_entity_id", "extracted_entities", "id") in foreign_keys


def test_extracted_entity_tracks_staged_resolution_state() -> None:
    columns = set(ExtractedEntity.__table__.columns.keys())
    foreign_keys = {
        (fk.parent.name, fk.column.table.name, fk.column.name)
        for fk in ExtractedEntity.__table__.foreign_keys
    }

    assert "resolution_status" in columns
    assert "resolved_at" in columns
    assert ("resolved_canonical_entity_id", "canonical_entities", "id") in foreign_keys
    assert (
        "resolved_by_candidate_id",
        "entity_resolution_candidates",
        "id",
    ) in foreign_keys
