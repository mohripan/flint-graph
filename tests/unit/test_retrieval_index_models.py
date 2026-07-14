from sqlalchemy import Index, UniqueConstraint

from atlas_rag.infrastructure.db.models import ChunkEmbedding, RetrievalIndexVersion


def test_retrieval_index_version_model_declares_active_scope_indexes() -> None:
    indexes = {
        index.name: index
        for index in RetrievalIndexVersion.__table__.indexes
        if isinstance(index, Index)
    }

    assert "uq_retrieval_index_versions_active_global" in indexes
    assert indexes["uq_retrieval_index_versions_active_global"].unique
    assert "uq_retrieval_index_versions_active_tenant" in indexes
    assert indexes["uq_retrieval_index_versions_active_tenant"].unique


def test_chunk_embedding_model_declares_idempotency_constraint() -> None:
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in ChunkEmbedding.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert (
        "retrieval_index_version_id",
        "document_version_id",
        "chunk_id",
        "chunk_hash",
    ) in unique_columns
