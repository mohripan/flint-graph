from sqlalchemy import UniqueConstraint

from atlas_rag.infrastructure.db.models import IngestionJob, QueryAnswerClaim, QueryRun


def test_ingestion_job_model_enforces_one_job_per_document_version() -> None:
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in IngestionJob.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("document_version_id",) in unique_columns


def test_query_run_model_includes_answer_faithfulness_summary_columns() -> None:
    columns = QueryRun.__table__.columns

    for expected in [
        "abstained",
        "abstain_reason",
        "supported_claim_count",
        "unsupported_claim_count",
        "support_method",
        "answer_provider",
    ]:
        assert expected in columns


def test_query_answer_claim_model_enforces_one_claim_index_per_run() -> None:
    unique_constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in QueryAnswerClaim.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert unique_constraints["uq_query_answer_claims_run_index"] == (
        "query_run_id",
        "claim_index",
    )
