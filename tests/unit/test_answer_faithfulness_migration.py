from pathlib import Path


def test_answer_faithfulness_migration_declares_expected_columns_and_table() -> None:
    migration = Path("migrations/versions/0011_answer_faithfulness.py")

    assert migration.exists()

    text = migration.read_text(encoding="utf-8")
    for expected in [
        '"query_runs"',
        '"abstained"',
        '"abstain_reason"',
        '"supported_claim_count"',
        '"unsupported_claim_count"',
        '"support_method"',
        '"answer_provider"',
        '"query_answer_claims"',
        "uq_query_answer_claims_run_index",
        "ix_query_answer_claims_run_index",
        "ix_query_answer_claims_tenant_status",
    ]:
        assert expected in text
