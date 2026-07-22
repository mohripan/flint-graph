from sqlalchemy import UniqueConstraint

from flint_graph.infrastructure.db.base import Base
from flint_graph.infrastructure.db.models import (
    CanonicalEntity,
    EntityAlias,
    EntityRelationship,
)


def _unique_column_sets(model: type) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in model.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_all_graph_tables_are_registered() -> None:
    tables = set(Base.metadata.tables)
    expected = {
        "canonical_entities",
        "entity_aliases",
        "entity_mentions",
        "claims",
        "entity_relationships",
        "merge_candidates",
        "merge_decisions",
    }
    assert expected <= tables


def test_canonical_entity_merged_into_is_a_self_reference() -> None:
    foreign_keys = {
        (fk.parent.name, fk.column.table.name, fk.column.name)
        for fk in CanonicalEntity.__table__.foreign_keys
    }
    assert ("merged_into_id", "canonical_entities", "id") in foreign_keys


def test_entity_alias_is_unique_per_entity_and_form() -> None:
    assert ("tenant_id", "canonical_entity_id", "normalized_form") in _unique_column_sets(
        EntityAlias
    )


def test_entity_relationship_is_unique_per_triple() -> None:
    assert (
        "tenant_id",
        "subject_entity_id",
        "predicate",
        "object_entity_id",
    ) in _unique_column_sets(EntityRelationship)
