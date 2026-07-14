from pathlib import Path

import yaml


def test_compose_declares_opensearch_service_and_internal_url() -> None:
    compose = yaml.safe_load(Path("compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert "opensearch" in services
    assert services["opensearch"]["image"].startswith("opensearchproject/opensearch:")
    assert "9200:9200" in services["opensearch"]["ports"]

    for service_name in ["api", "ingestion-worker"]:
        environment = services[service_name]["environment"]
        assert environment["ATLAS_OPENSEARCH_URL"] == "http://opensearch:9200"
        assert services[service_name]["depends_on"]["opensearch"]["condition"] == "service_healthy"
