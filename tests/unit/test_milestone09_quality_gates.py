from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_ci_checks_default_branch_pushes_and_frontend_behavior() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    assert "master" in workflow["on"]["push"]["branches"]
    steps = workflow["jobs"]["frontend-check"]["steps"]
    commands = "\n".join(step.get("run", "") for step in steps)
    assert "npm ci" in commands
    assert "npm test" in commands
    assert "npm run typecheck" in commands
    assert "npm run build" in commands


def test_make_check_runs_offline_eval_gate() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert ".PHONY:" in makefile and "eval-gate" in makefile
    assert "eval-gate:" in makefile
    assert "uv run flint-graph-eval run" in makefile
    assert "--dataset evals/datasets/acme-smoke" in makefile
    assert "--evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl" in makefile
    assert "--experiment evals/experiments/acme-smoke.yaml" in makefile
    assert "--baseline evals/reports/acme-smoke/baselines.json" in makefile
    assert "check: lint typecheck test eval-gate" in makefile


def test_repository_offline_eval_gate_fixture_passes() -> None:
    command = [
        "uv",
        "run",
        "flint-graph-eval",
        "run",
        "--dataset",
        "evals/datasets/acme-smoke",
        "--evaluations",
        "evals/reports/acme-smoke/deterministic-recorded.jsonl",
        "--experiment",
        "evals/experiments/acme-smoke.yaml",
        "--baseline",
        "evals/reports/acme-smoke/baselines.json",
        "--config-name",
        "deterministic",
        "--created-at",
        "2026-07-14T00:00:00Z",
    ]

    result = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "deterministic @ acme-smoke v1" in result.stdout


def test_ci_workflows_define_offline_and_secrets_gated_live_eval() -> None:
    pr_workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    live_workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "live-eval.yml").read_text(encoding="utf-8")
    )

    pr_commands = "\n".join(
        step.get("run", "")
        for job in pr_workflow["jobs"].values()
        for step in job.get("steps", [])
    )
    assert "uv run pytest" in pr_commands
    assert "uv run flint-graph-eval run" in pr_commands
    assert "ANTHROPIC_API_KEY" not in pr_commands

    live_commands = "\n".join(
        step.get("run", "")
        for job in live_workflow["jobs"].values()
        for step in job.get("steps", [])
    )
    live_env = {
        key
        for job in live_workflow["jobs"].values()
        for key in job.get("env", {})
    }
    assert "schedule" in live_workflow["on"]
    assert "workflow_dispatch" in live_workflow["on"]
    assert "FLINT_GRAPH_EVAL_TOKEN" in live_env
    assert "ANTHROPIC_API_KEY" not in live_env
    assert "uv run flint-graph-eval nightly" in live_commands
    assert "UNCONFIGURED" in live_commands


def test_compose_local_services_are_no_cost_by_default() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    settings_services = ["api", "outbox-relay", "ingestion-worker", "migrate", "neo4j-migrate"]

    for service_name in settings_services:
        environment = compose["services"][service_name]["environment"]
        assert _compose_default(environment["FLINT_GRAPH_QUERY_ANSWER_PROVIDER"]) == "deterministic"
        assert (
            _compose_default(environment["FLINT_GRAPH_QUERY_SUPPORT_PROVIDER"])
            == "deterministic"
        )
        assert _compose_default(environment["FLINT_GRAPH_EMBEDDING_PROVIDER"]) == "deterministic"


def test_env_example_is_no_cost_by_default() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "\nFLINT_GRAPH_EMBEDDING_PROVIDER=deterministic\n" in env_example
    assert "\nFLINT_GRAPH_QUERY_ANSWER_PROVIDER=deterministic\n" in env_example
    assert "\nFLINT_GRAPH_QUERY_SUPPORT_PROVIDER=deterministic\n" in env_example


def _compose_default(value: str) -> str:
    if value.startswith("${") and value.endswith("}") and ":-" in value:
        return value.removesuffix("}").split(":-", maxsplit=1)[1]
    return value
