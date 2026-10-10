"""Alert rules and dashboard panels must reference metrics that exist.

The metric names are derived by rendering the real exporter output rather than by
reimplementing its naming rules, so a renamed instrument or a changed unit fails
here instead of producing a silently empty dashboard.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from flint_graph.config import Settings
from flint_graph.observability import metrics
from flint_graph.observability.instruments import ALL_INSTRUMENTS, InstrumentKind

ALERTS = Path("ops/observability/alerts.yml")
DASHBOARD = Path("ops/observability/grafana-dashboard.json")
PROMETHEUS_CONFIG = Path("ops/observability/prometheus.yml")


def test_alerts_reach_an_opt_in_loopback_alertmanager_without_external_delivery() -> None:
    compose = yaml.safe_load(Path("compose.yaml").read_text(encoding="utf-8"))
    service = compose["services"]["alertmanager"]
    assert service["profiles"] == ["metrics"]
    assert service["ports"] == ["127.0.0.1:9093:9093"]
    assert service["image"].startswith("prom/alertmanager:v")
    assert "latest" not in service["image"]
    assert "alertmanager_data:/alertmanager" in service["volumes"]
    prometheus = yaml.safe_load(PROMETHEUS_CONFIG.read_text(encoding="utf-8"))
    targets = prometheus["alerting"]["alertmanagers"][0]["static_configs"][0]["targets"]
    assert targets == ["alertmanager:9093"]
    config = yaml.safe_load(Path("ops/observability/alertmanager.yml").read_text("utf-8"))
    assert config["route"]["group_by"] == ["alertname", "service"]
    assert config["route"]["receiver"] == "local-no-delivery"
    assert config["receivers"] == [{"name": "local-no-delivery"}]
    assert config["inhibit_rules"][0]["equal"] == ["alertname", "service"]

# Names that appear in queries but are produced by PromQL, not by our exporter.
_PROMQL_FUNCTIONS = frozenset(
    {
        "sum",
        "rate",
        "increase",
        "histogram_quantile",
        "clamp_min",
        "topk",
        "by",
        "le",
        "on",
        "without",
        "and",
        "or",
        "unless",
    }
)

_METRIC_TOKEN = re.compile(r"\bflint_graph_[a-z0-9_]+")


_LABEL_TOKEN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=")


@pytest.fixture(scope="module")
def exported_names() -> frozenset[str]:
    """Render every instrument once and collect exported series and label names.

    Both are needed: a query references metrics and the labels it groups or
    filters by, and a mistyped label is as broken as a mistyped metric.
    """
    metrics.reset_metrics()
    metrics.configure_metrics(Settings(env="test", metrics_enabled=True, otel_enabled=False))
    for spec in ALL_INSTRUMENTS:
        attributes = {key: "sample" for key in spec.attribute_keys}
        match spec.kind:
            case InstrumentKind.COUNTER:
                metrics.add(spec, 1, **attributes)
            case InstrumentKind.HISTOGRAM:
                metrics.record(spec, 1.0, **attributes)
            case InstrumentKind.GAUGE:
                metrics.set_gauge(spec, 1, **attributes)

    payload, _content_type = metrics.render_prometheus_metrics()
    names: set[str] = set()
    for line in payload.decode("utf-8").splitlines():
        if line.startswith("# TYPE "):
            name = line.split()[2]
            names.add(name)
            # Histograms are queried through their derived series.
            names.update({f"{name}_bucket", f"{name}_count", f"{name}_sum"})
        elif line.startswith("flint_graph_") and "{" in line:
            labels = line[line.index("{") + 1 : line.rindex("}")]
            names.update(_LABEL_TOKEN.findall(labels))
    metrics.reset_metrics()
    return frozenset(names)


def _referenced_metrics(text: str) -> set[str]:
    return {
        token
        for token in _METRIC_TOKEN.findall(text)
        if token not in _PROMQL_FUNCTIONS
    }


def test_alert_rules_are_valid_yaml_with_required_fields() -> None:
    document = yaml.safe_load(ALERTS.read_text(encoding="utf-8"))

    assert document["groups"]
    for group in document["groups"]:
        assert group["name"].startswith("flint-graph")
        for rule in group["rules"]:
            assert rule["alert"]
            assert rule["expr"]
            assert rule["for"]
            assert rule["labels"]["severity"] in {"page", "ticket"}
            # Every alert must say what to do about it.
            assert rule["annotations"]["summary"]
            assert rule["annotations"]["runbook"].startswith(
                "docs/runbooks/operations-observability.md#"
            )


def test_every_alert_expression_references_exported_names(
    exported_names: frozenset[str],
) -> None:
    document = yaml.safe_load(ALERTS.read_text(encoding="utf-8"))

    for group in document["groups"]:
        for rule in group["rules"]:
            referenced = _referenced_metrics(rule["expr"])
            assert referenced, rule["alert"]
            unknown = referenced - exported_names
            assert not unknown, f"{rule['alert']} references unknown names: {unknown}"


def test_every_dashboard_target_references_exported_names(
    exported_names: frozenset[str],
) -> None:
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))

    checked = 0
    for panel in dashboard["panels"]:
        for target in panel.get("targets", []):
            referenced = _referenced_metrics(target["expr"])
            assert referenced, f"{panel['title']} / {target['refId']}"
            unknown = referenced - exported_names
            assert not unknown, f"{panel['title']} references unknown names: {unknown}"
            checked += 1

    assert checked >= 15


def test_dashboard_panels_are_uniquely_identified_and_titled() -> None:
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))

    ids = [panel["id"] for panel in dashboard["panels"]]
    assert len(ids) == len(set(ids))
    assert dashboard["uid"] == "flint-graph-operations"
    assert all(panel["title"] for panel in dashboard["panels"])


def test_operations_dashboard_is_provisioned_with_a_default_datasource_and_clear_units() -> None:
    compose = yaml.safe_load(Path("compose.yaml").read_text("utf-8"))
    volumes = compose["services"]["observability"]["volumes"]
    assert any("grafana/provisioning/dashboards" in mount for mount in volumes)
    assert any("grafana/provisioning/datasources" in mount for mount in volumes)
    assert any("grafana-dashboard.json" in mount for mount in volumes)
    provisioning = yaml.safe_load(
        Path("ops/observability/grafana/provisioning/dashboards/flint-graph.yml").read_text("utf-8")
    )
    assert provisioning["providers"][0]["folder"] == "FlintGraph"
    assert provisioning["providers"][0]["disableDeletion"] is True
    datasource = yaml.safe_load(
        Path("ops/observability/grafana/provisioning/datasources/flint-graph.yml").read_text("utf-8")
    )["datasources"][0]
    assert datasource["uid"] == "flint-graph-metrics"
    assert datasource["url"] == "http://127.0.0.1:9090"
    dashboard = json.loads(DASHBOARD.read_text("utf-8"))
    assert dashboard["templating"]["list"][0]["current"]["value"] == datasource["uid"]
    for panel in dashboard["panels"]:
        targets = panel.get("targets", [])
        if not targets:
            continue
        expressions = " ".join(target["expr"] for target in targets)
        if "histogram_quantile" in expressions:
            assert all("histogram_quantile" in target["expr"] for target in targets)
            assert panel["fieldConfig"]["defaults"]["unit"] == "ms"
        assert panel["fieldConfig"]["defaults"]["noValue"] == "No samples"


def test_alert_runbook_anchors_exist_in_the_runbook() -> None:
    """A runbook link that goes nowhere is worse than no link."""
    runbook = Path("docs/runbooks/operations-observability.md")
    text = runbook.read_text(encoding="utf-8").casefold()
    document = yaml.safe_load(ALERTS.read_text(encoding="utf-8"))

    for group in document["groups"]:
        for rule in group["rules"]:
            anchor = rule["annotations"]["runbook"].split("#", 1)[1]
            heading = anchor.replace("-", " ")
            assert heading in text, f"{rule['alert']} anchor '{anchor}' is missing"


def test_prometheus_config_scrapes_the_api_metrics_path() -> None:
    document = yaml.safe_load(PROMETHEUS_CONFIG.read_text(encoding="utf-8"))

    jobs = {job["job_name"]: job for job in document["scrape_configs"]}
    assert "flint-graph-api" in jobs
    assert jobs["flint-graph-api"]["metrics_path"] == "/metrics"
    # The endpoint is token-gated, so a scrape config without auth would 401.
    assert jobs["flint-graph-api"]["authorization"]["type"] == "Bearer"
    assert document["rule_files"] == ["/etc/prometheus/alerts.yml"]
