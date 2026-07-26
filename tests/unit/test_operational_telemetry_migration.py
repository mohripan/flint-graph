"""Migration 0015 must match the ORM models it backs.

The string assertions follow the house style for migration tests; the parity
check is the one that catches drift, since SQLite-backed tests create schema
from the models and would never notice a missing migration column.
"""

from pathlib import Path

from sqlalchemy import inspect

from flint_graph.infrastructure.db.models import AuditEvent, ProviderUsageEvent, QueryRun

MIGRATION = Path("migrations/versions/0015_operational_telemetry.py")


def _migration_text() -> str:
    assert MIGRATION.exists()
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_declares_expected_tables_and_indexes() -> None:
    text = _migration_text()

    for expected in [
        '"audit_events"',
        '"provider_usage_events"',
        "ix_audit_events_tenant_created",
        "ix_audit_events_actor_created",
        "ix_audit_events_action_created",
        "ix_provider_usage_events_tenant_created",
        "ix_provider_usage_events_tenant_operation_created",
        "ix_provider_usage_events_query_run",
        "ck_provider_usage_input_tokens",
        "ck_provider_usage_output_tokens",
    ]:
        assert expected in text


def test_migration_adds_query_run_usage_rollups() -> None:
    text = _migration_text()

    for expected in [
        '"provider_input_tokens"',
        '"provider_output_tokens"',
        '"provider_duration_ms"',
        '"provider_cost_micros"',
    ]:
        assert expected in text
    # Existing rows predate accounting, so the new counters must backfill to zero.
    assert 'server_default="0"' in text


def test_migration_is_reversible() -> None:
    text = _migration_text()

    assert "def downgrade() -> None:" in text
    for expected in [
        'op.drop_table("audit_events")',
        'op.drop_table("provider_usage_events")',
        'op.drop_column("query_runs", "provider_cost_micros")',
    ]:
        assert expected in text


def test_migration_columns_match_the_orm_models() -> None:
    text = _migration_text()

    for model in (AuditEvent, ProviderUsageEvent):
        for column in inspect(model).columns:
            assert f'"{column.name}"' in text, f"{model.__tablename__}.{column.name}"

    rollups = {
        "provider_input_tokens",
        "provider_output_tokens",
        "provider_duration_ms",
        "provider_cost_micros",
    }
    model_columns = {column.name for column in inspect(QueryRun).columns}
    assert rollups <= model_columns


def test_audit_action_enum_values_are_all_migrated() -> None:
    """A new audit action without a migrated enum value fails inserts at runtime."""
    from flint_graph.domain.enums import AuditAction, AuditOutcome, ProviderUsageOperation

    text = _migration_text()
    for member in [*AuditAction, *AuditOutcome, *ProviderUsageOperation]:
        assert f'"{member.value}"' in text, member.value
