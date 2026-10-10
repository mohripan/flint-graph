"""Validate the public deployment contract for opt-in AI telemetry."""

from pathlib import Path

import yaml


def test_phoenix_is_opt_in_loopback_persistent_and_not_a_metrics_backend() -> None:
    compose = yaml.safe_load(Path("compose.ai-observability.yaml").read_text("utf-8"))
    phoenix = compose["services"]["phoenix"]
    assert phoenix["profiles"] == ["ai-observability"]
    assert phoenix["ports"] == ["127.0.0.1:6006:6006"]
    assert phoenix["image"] == "arizephoenix/phoenix:20.20.0"
    assert phoenix["volumes"] == ["phoenix_data:/mnt/data"]
    gateway = compose["services"]["otel-gateway"]
    assert gateway["ports"] == ["127.0.0.1:14317:4317"]
    assert gateway["mem_limit"] == "768m"
    config = yaml.safe_load(Path("ops/observability/otel-gateway.yml").read_text("utf-8"))
    pipelines = config["service"]["pipelines"]
    assert pipelines["traces"]["exporters"] == ["otlp/lgtm", "otlp/phoenix"]
    assert pipelines["metrics"]["exporters"] == ["otlp/lgtm"]
    assert pipelines["logs"]["exporters"] == ["otlp/lgtm"]
    assert pipelines["traces"]["processors"] == [
        "memory_limiter", "filter/drop_events", "transform/privacy", "batch"
    ]
    assert config["processors"]["transform/privacy"]["error_mode"] == "propagate"
    statements = config["processors"]["transform/privacy"]["trace_statements"]
    span_statements = next(
        group["statements"] for group in statements if group["context"] == "span"
    )
    assert any(statement.startswith("keep_keys(attributes,") for statement in span_statements)
    assert 'set(status.message, "")' in span_statements
    assert config["processors"]["filter/drop_events"]["traces"]["spanevent"] == ["true"]
    for exporter in config["exporters"].values():
        assert exporter["sending_queue"]["queue_size"] == 256
        assert exporter["retry_on_failure"]["max_elapsed_time"] == "60s"


def test_ci_checks_native_configs_rejects_invalid_assets_and_runs_real_privacy_smoke() -> None:
    workflow = yaml.safe_load(Path(".github/workflows/ci.yml").read_text("utf-8"))
    job = workflow["jobs"]["observability-check"]
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    for command in ("promtool", "amtool", "otel-gateway validate"):
        assert command in commands
    for name in ("invalid-alerts.yml", "invalid-alertmanager.yml", "invalid-collector.yml"):
        assert name in commands
    assert "tests/integration/test_ai_observability_live.py" in commands
    assert job["timeout-minutes"] == 15
    assert any(
        step.get("env", {}).get("FLINT_GRAPH_AI_OBSERVABILITY_INTEGRATION") == "1"
        for step in job["steps"]
    )
