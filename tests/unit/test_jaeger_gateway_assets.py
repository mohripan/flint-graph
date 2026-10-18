"""Optional deployment contract; real fan-out/failure checks are opt-in."""

from pathlib import Path

import yaml


def load(name):
    return yaml.safe_load(Path(name).read_text("utf-8"))


def test_jaeger_gateway_reuses_privacy_and_requires_explicit_destination_selection():
    overlay = load("compose.jaeger-gateway.yaml")
    gateway = overlay["services"]["otel-gateway"]
    assert gateway["image"] == "otel/opentelemetry-collector-contrib:0.162.0"
    assert gateway["profiles"] == ["jaeger"]
    assert gateway["mem_limit"] == "768m"
    assert gateway["ports"] == ["127.0.0.1:14317:4317", "127.0.0.1:18888:8888"]
    assert gateway["command"] == [
        "--config=/etc/otelcol/config.yml",
        "--config=/etc/otelcol/jaeger-exporter.yml",
        "--config=/etc/otelcol/${FLINT_GRAPH_JAEGER_GATEWAY_MODE:-jaeger-only}.yml",
    ]
    assert gateway["volumes"] == [
        "./ops/observability/otel-gateway.yml:/etc/otelcol/config.yml:ro",
        "./ops/observability/otel-jaeger-exporter.yml:/etc/otelcol/jaeger-exporter.yml:ro",
        "./ops/observability/otel-jaeger-only.yml:/etc/otelcol/jaeger-only.yml:ro",
        "./ops/observability/otel-jaeger-phoenix.yml:/etc/otelcol/jaeger-phoenix.yml:ro",
    ]
    for mode, destinations in (
        ("jaeger-only", ["otlp/lgtm", "otlp/jaeger"]),
        ("jaeger-phoenix", ["otlp/lgtm", "otlp/phoenix", "otlp/jaeger"]),
    ):
        assert load(f"ops/observability/otel-{mode}.yml") == {
            "service": {"pipelines": {"traces": {"exporters": destinations}}}
        }
    extra = load("ops/observability/otel-jaeger-exporter.yml")
    assert "processors" not in extra and "pipelines" not in extra["service"]
    exporter = extra["exporters"]["otlp/jaeger"]
    assert exporter["endpoint"] == "jaeger:4317"
    assert exporter["timeout"] == "2s"
    assert exporter["sending_queue"] == {
        "enabled": True,
        "num_consumers": 2,
        "queue_size": 64,
        "sizer": "requests",
        "block_on_overflow": False,
        "wait_for_result": False,
    }
    assert exporter["retry_on_failure"] == {
        "enabled": True,
        "initial_interval": "1s",
        "max_interval": "2s",
        "max_elapsed_time": "10s",
    }
    shared = load("ops/observability/otel-gateway.yml")
    for signal in ("metrics", "logs"):
        assert shared["service"]["pipelines"][signal]["exporters"] == ["otlp/lgtm"]
    assert shared["processors"]["transform/privacy"]["error_mode"] == "propagate"
    assert shared["processors"]["filter/drop_events"]["error_mode"] == "propagate"


def test_optional_grafana_jaeger_is_fixed_nondefault_and_pruned_on_removal():
    overlay = load("compose.jaeger-gateway.yaml")
    assert overlay["services"]["observability"]["volumes"] == [
        "./ops/observability/grafana/provisioning/datasources/jaeger.yml:"
        "/otel-lgtm/grafana/conf/provisioning/datasources/jaeger.yml:ro"
    ]
    config = load("ops/observability/grafana/provisioning/datasources/jaeger.yml")
    assert config["prune"] is True
    assert config["datasources"] == [
        {
            "name": "FlintGraph Jaeger",
            "uid": "flint-graph-jaeger",
            "type": "jaeger",
            "access": "proxy",
            "url": "http://jaeger:16686",
            "isDefault": False,
            "editable": False,
        }
    ]
