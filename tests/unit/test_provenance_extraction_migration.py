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
