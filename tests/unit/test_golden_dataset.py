from __future__ import annotations

from pathlib import Path

from flint_graph.evaluation import load_dataset

_DATASET_DIR = Path(__file__).resolve().parents[2] / "evals" / "datasets" / "acme-smoke"


def _corpus_external_ids() -> set[str]:
    metadata_dir = _DATASET_DIR / "corpus"
    return {path.stem for path in metadata_dir.glob("*.md")}


def test_acme_smoke_dataset_loads() -> None:
    dataset = load_dataset(_DATASET_DIR)

    assert dataset.metadata.name == "acme-smoke"
    assert dataset.metadata.tenant == "eval-acme"
    assert len(dataset.queries) >= 8


def test_acme_smoke_covers_all_query_types() -> None:
    dataset = load_dataset(_DATASET_DIR)

    types = {query.query_type for query in dataset.queries}
    assert types == {"factoid", "multi_hop", "entity", "abstain_expected"}


def test_acme_smoke_labels_reference_real_corpus_documents() -> None:
    dataset = load_dataset(_DATASET_DIR)
    corpus_ids = _corpus_external_ids()
    assert corpus_ids, "corpus directory must contain documents"

    for query in dataset.queries:
        for external_id in query.relevant_chunk_ids:
            assert external_id in corpus_ids, (
                f"{query.id}: relevant_chunk_id '{external_id}' has no corpus document"
            )
        for external_id in query.must_cite_sources:
            assert external_id in corpus_ids, (
                f"{query.id}: must_cite_sources '{external_id}' has no corpus document"
            )


def test_acme_smoke_query_shapes_are_consistent() -> None:
    dataset = load_dataset(_DATASET_DIR)

    for query in dataset.queries:
        if query.expect_abstain:
            assert query.expected_answer is None
            assert not query.relevant_chunk_ids
        else:
            assert query.expected_answer is not None
        if query.query_type == "entity":
            assert query.relevant_entity_ids
