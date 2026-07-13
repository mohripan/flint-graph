from pathlib import Path


def test_provenance_extraction_migration_declares_expected_tables() -> None:
    migration = Path("migrations/versions/0006_provenance_extraction.py")

    assert migration.exists()

    text = migration.read_text(encoding="utf-8")
    for table_name in [
        "extraction_runs",
        "extraction_invocations",
        "extraction_artifacts",
        "evidence_spans",
        "extracted_entities",
        "extracted_relations",
        "extracted_claims",
        "entity_resolution_candidates",
    ]:
        assert f'"{table_name}"' in text


def test_staged_resolution_migration_declares_resolution_columns() -> None:
    migration = Path("migrations/versions/0007_staged_resolution_state.py")

    assert migration.exists()

    text = migration.read_text(encoding="utf-8")
    for column_name in [
        "resolution_status",
        "resolved_canonical_entity_id",
        "resolved_by_candidate_id",
        "resolved_at",
    ]:
        assert f'"{column_name}"' in text
