from pathlib import Path


def test_query_run_ledger_migration_declares_expected_tables_and_constraints() -> None:
    migration = Path("migrations/versions/0010_query_run_ledger.py")

    assert migration.exists()

    text = migration.read_text(encoding="utf-8")
    for expected in [
        '"query_runs"',
        '"query_run_events"',
        '"query_run_linked_entities"',
        '"query_run_candidates"',
        '"query_context_packs"',
        "uq_query_run_events_run_sequence",
        "uq_query_run_candidates_run_dedupe",
        "uq_query_context_packs_run_version",
        "ix_query_runs_tenant_status_created",
        "ix_query_run_events_run_sequence",
    ]:
        assert expected in text
