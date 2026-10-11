"""Public deployment contract; native/runtime qualification is separate."""

from pathlib import Path

import yaml


def test_jaeger_backend_is_explicitly_opt_in_pinned_loopback_and_bounded():
    overlay = yaml.safe_load(Path("compose.jaeger.yaml").read_text("utf-8"))
    assert set(overlay["services"]) == {"jaeger"}
    service = overlay["services"]["jaeger"]
    assert service["profiles"] == ["jaeger"]
    assert service["image"] == (
        "cr.jaegertracing.io/jaegertracing/jaeger:2.22.0@"
        "sha256:836b967b5abcf1f7758066aa6b348619267a2f1459f72d472840570f9bd88a17"
    )
    assert service["ports"] == ["127.0.0.1:16686:16686"]
    assert service["mem_limit"] == "512m"
    assert service["cpus"] == 1.0
    assert service["pids_limit"] == 128
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["command"] == ["--config=/etc/jaeger/config.yml"]
    assert service["volumes"] == ["./ops/observability/jaeger.yml:/etc/jaeger/config.yml:ro"]
    assert service["healthcheck"]["test"] == [
        "CMD",
        "wget",
        "-q",
        "--spider",
        "http://127.0.0.1:13133/health/status",
    ]
    assert "volumes" not in overlay
    config = yaml.safe_load(Path("ops/observability/jaeger.yml").read_text("utf-8"))
    assert set(config["receivers"]) == {"otlp"}
    assert set(config["receivers"]["otlp"]["protocols"]) == {"grpc"}
    assert config["receivers"]["otlp"]["protocols"]["grpc"]["endpoint"] == "0.0.0.0:4317"
    assert set(config["extensions"]) == {"jaeger_storage", "jaeger_query", "healthcheckv2"}
    query = config["extensions"]["jaeger_query"]
    assert "ai" not in query
    assert "otlp_proxy" not in query
    assert (
        config["extensions"]["jaeger_storage"]["backends"]["local"]["memory"]["max_traces"]
        == 10_000
    )
    assert config["processors"]["memory_limiter"]["limit_mib"] == 384
    assert config["processors"]["batch"]["send_batch_max_size"] == 512
    assert set(config["service"]["pipelines"]) == {"traces"}
    assert config["exporters"]["jaeger_storage_exporter"]["queue"]["queue_size"] == 128
