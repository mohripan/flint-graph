import importlib

import pytest


def test_project_identity_uses_flintgraph_names() -> None:
    try:
        config_module = importlib.import_module("flint_graph.config")
        main_module = importlib.import_module("flint_graph.main")
    except ModuleNotFoundError as exc:
        pytest.fail(f"FlintGraph package import failed: {exc}")

    settings = config_module.Settings()

    assert config_module.Settings.model_config["env_prefix"] == "FLINT_GRAPH_"
    assert settings.service_name == "flint-graph-api"
    assert main_module.app.title == "FlintGraph API"
