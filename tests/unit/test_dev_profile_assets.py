from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_offline_overlay_explicitly_disables_external_model_providers():
    config = yaml.safe_load((ROOT / "compose.offline.yaml").read_text())
    for role in ("api", "ingestion-worker", "outbox-relay"):
        environment = config["services"][role]["environment"]
        assert environment["FLINT_GRAPH_LLM_PROVIDER"] == "deterministic"
        assert environment["FLINT_GRAPH_EMBEDDING_PROVIDER"] == "deterministic"
        assert environment["FLINT_GRAPH_EMBEDDING_MODEL"] == "deterministic-test"
        assert environment["FLINT_GRAPH_EMBEDDING_DIMENSIONS"] == "384"
        assert environment["FLINT_GRAPH_QUERY_ANSWER_PROVIDER"] == "deterministic"
        assert environment["FLINT_GRAPH_QUERY_SUPPORT_PROVIDER"] == "deterministic"


def test_local_real_overlay_requires_explicit_models_dimensions_and_keeps_extraction_offline():
    config = yaml.safe_load((ROOT / "compose.local-real.yaml").read_text())
    for role in ("api", "ingestion-worker", "outbox-relay"):
        environment = config["services"][role]["environment"]
        assert environment["FLINT_GRAPH_LLM_PROVIDER"] == "deterministic"
        assert environment["FLINT_GRAPH_EMBEDDING_PROVIDER"] == "ollama"
        assert environment["FLINT_GRAPH_QUERY_ANSWER_PROVIDER"] == "ollama"
        assert environment["FLINT_GRAPH_QUERY_SUPPORT_PROVIDER"] == "ollama"
        for field in (
            "FLINT_GRAPH_EMBEDDING_MODEL",
            "FLINT_GRAPH_EMBEDDING_DIMENSIONS",
            "FLINT_GRAPH_QUERY_ANSWER_MODEL",
            "FLINT_GRAPH_QUERY_SUPPORT_MODEL",
        ):
            assert ":?" in environment[field]
