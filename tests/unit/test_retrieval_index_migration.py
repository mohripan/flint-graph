from pathlib import Path


def test_retrieval_index_ledger_migration_declares_expected_tables_and_indexes() -> None:
    migration = Path("migrations/versions/0008_retrieval_index_ledger.py")

    assert migration.exists()

    text = migration.read_text(encoding="utf-8")
    for expected in [
        '"retrieval_index_versions"',
        '"chunk_embeddings"',
        '"index_backfill_jobs"',
        "uq_retrieval_index_versions_active_global",
        "uq_retrieval_index_versions_active_tenant",
        "uq_chunk_embeddings_index_chunk_hash",
    ]:
        assert expected in text


def test_document_index_coverage_migration_declares_expected_table_and_constraints() -> None:
    migration = Path("migrations/versions/0009_document_index_coverage.py")

    assert migration.exists()

    text = migration.read_text(encoding="utf-8")
    for expected in [
        '"document_index_coverages"',
        "uq_document_index_coverages_version_document_version",
        "ix_document_index_coverages_tenant_status",
        "ix_document_index_coverages_document_version",
    ]:
        assert expected in text
