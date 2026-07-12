from sqlalchemy import UniqueConstraint

from atlas_rag.infrastructure.db.models import IngestionJob


def test_ingestion_job_model_enforces_one_job_per_document_version() -> None:
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in IngestionJob.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("document_version_id",) in unique_columns
