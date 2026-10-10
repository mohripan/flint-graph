from pathlib import Path

import yaml


def test_nightly_workflow_is_fresh_serialized_opt_in_and_only_publishes_redacted_report():
    workflow = yaml.safe_load(Path(".github/workflows/live-eval.yml").read_text())
    assert set(workflow["on"]) == {"schedule", "workflow_dispatch"}
    assert workflow["concurrency"]["cancel-in-progress"] is False
    job = workflow["jobs"]["financial-black-box"]
    assert "FLINT_GRAPH_RUN_LIVE_EVAL" in job["if"]
    assert job["timeout-minutes"] <= 30
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert "flint-graph-eval nightly" in commands
    assert "flint-graph-corpus download" in commands
    assert "ANTHROPIC_API_KEY" not in commands
    upload = next(
        step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact")
    )
    assert upload["with"]["path"] == "notes/nightly-report.json"
    assert upload["with"]["retention-days"] <= 7
