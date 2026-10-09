from __future__ import annotations

import asyncio
import json
from pathlib import Path

from flint_graph.cli.eval import main
from flint_graph.evaluation import (
    GoldenDataset,
    load_dataset,
    load_experiment,
    load_recorded_evaluations,
    recorded_evaluator,
    run_comparison,
)
from flint_graph.evaluation.comparison import comparison_table

_GOOD = [
    {
        "query_id": "q1",
        "evaluation": {
            "retrieved_chunk_ids": ["doc-a"],
            "answer_text": "It is Berlin.",
            "cited_source_ids": ["doc-a"],
            "supported_claim_count": 1,
            "latency_ms": 50.0,
        },
    },
    {"query_id": "q2", "evaluation": {"abstained": True}},
]
_WORSE = [
    {
        "query_id": "q1",
        "evaluation": {
            "retrieved_chunk_ids": ["doc-x"],
            "answer_text": "It is Paris.",
            "cited_source_ids": [],
            "unsupported_claim_count": 1,
        },
    },
    {"query_id": "q2", "evaluation": {"answer_text": "fabricated", "supported_claim_count": 1}},
]


def _write_dataset(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "dataset.yaml").write_text("name: mini\nversion: 1\ntenant: t\n", encoding="utf-8")
    queries = [
        {
            "id": "q1",
            "query": "Where is Acme headquartered?",
            "query_type": "factoid",
            "expected_answer": "Berlin",
            "relevant_chunk_ids": ["doc-a"],
            "must_cite_sources": ["doc-a"],
        },
        {
            "id": "q2",
            "query": "Unknowable?",
            "query_type": "abstain_expected",
            "expect_abstain": True,
        },
    ]
    (directory / "queries.jsonl").write_text(
        "\n".join(json.dumps(query) for query in queries) + "\n", encoding="utf-8"
    )
    return directory


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> Path:
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
    return path


def test_load_experiment_parses_thresholds(tmp_path: Path) -> None:
    path = tmp_path / "exp.yaml"
    path.write_text(
        "dataset: mini\nk_values: [1]\nthresholds:\n  recall@1:\n    min: 0.7\n",
        encoding="utf-8",
    )

    experiment = load_experiment(path)

    assert experiment.dataset == "mini"
    assert experiment.k_values == [1]
    assert experiment.thresholds["recall@1"].min == 0.7


def test_recorded_evaluator_round_trip(tmp_path: Path) -> None:
    path = _write_jsonl(tmp_path / "rec.jsonl", _GOOD)

    recorded = load_recorded_evaluations(path)
    evaluator = recorded_evaluator(recorded)

    assert set(recorded) == {"q1", "q2"}
    dataset = load_dataset(_write_dataset(tmp_path / "ds"))
    evaluation = asyncio.run(evaluator(dataset.queries[0]))
    assert evaluation.answer_text == "It is Berlin."


def test_run_comparison_and_table(tmp_path: Path) -> None:
    dataset = load_dataset(_write_dataset(tmp_path / "ds"))
    good = recorded_evaluator(load_recorded_evaluations(_write_jsonl(tmp_path / "g.jsonl", _GOOD)))
    worse = recorded_evaluator(
        load_recorded_evaluations(_write_jsonl(tmp_path / "w.jsonl", _WORSE))
    )

    reports = asyncio.run(
        run_comparison(
            dataset=dataset,
            evaluators={"good": good, "worse": worse},
            created_at="2026-07-14T00:00:00Z",
            k_values=[1],
        )
    )

    assert set(reports) == {"good", "worse"}
    assert reports["good"].aggregate["recall@1"] == 1.0
    assert reports["worse"].aggregate["recall@1"] == 0.0
    table = comparison_table(reports)
    assert "| metric | good | worse |" in table
    assert "recall@1" in table


def test_cli_run_writes_report_and_passes(tmp_path: Path) -> None:
    dataset_dir = _write_dataset(tmp_path / "ds")
    recorded = _write_jsonl(tmp_path / "rec.jsonl", _GOOD)
    report_path = tmp_path / "report.json"

    exit_code = main(
        [
            "run",
            "--dataset",
            str(dataset_dir),
            "--evaluations",
            str(recorded),
            "--report",
            str(report_path),
            "--created-at",
            "2026-07-14T00:00:00Z",
            "--k",
            "1",
        ]
    )

    assert exit_code == 0
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["aggregate"]["recall@1"] == 1.0
    assert payload["run"]["query_count"] == 2


def test_cli_run_fails_on_threshold(tmp_path: Path) -> None:
    dataset_dir = _write_dataset(tmp_path / "ds")
    recorded = _write_jsonl(tmp_path / "rec.jsonl", _GOOD)
    experiment = tmp_path / "exp.yaml"
    experiment.write_text(
        "dataset: mini\nthresholds:\n  recall@1:\n    max: 0.5\n", encoding="utf-8"
    )

    exit_code = main(
        [
            "run",
            "--dataset",
            str(dataset_dir),
            "--evaluations",
            str(recorded),
            "--experiment",
            str(experiment),
            "--created-at",
            "2026-07-14T00:00:00Z",
            "--k",
            "1",
        ]
    )

    assert exit_code == 1


def test_cli_baseline_update_then_regression(tmp_path: Path) -> None:
    dataset_dir = _write_dataset(tmp_path / "ds")
    good = _write_jsonl(tmp_path / "good.jsonl", _GOOD)
    worse = _write_jsonl(tmp_path / "worse.jsonl", _WORSE)
    report_path = tmp_path / "report.json"
    baseline_path = tmp_path / "baseline.json"

    assert (
        main(
            [
                "run",
                "--dataset",
                str(dataset_dir),
                "--evaluations",
                str(good),
                "--report",
                str(report_path),
                "--created-at",
                "2026-07-14T00:00:00Z",
                "--k",
                "1",
            ]
        )
        == 0
    )
    update_exit = main(
        ["baseline", "update", "--report", str(report_path), "--baseline", str(baseline_path)]
    )
    assert update_exit == 0
    assert baseline_path.exists()

    regression_exit = main(
        [
            "run",
            "--dataset",
            str(dataset_dir),
            "--evaluations",
            str(worse),
            "--baseline",
            str(baseline_path),
            "--created-at",
            "2026-07-14T00:00:00Z",
            "--k",
            "1",
        ]
    )
    assert regression_exit == 1


def test_cli_compare_writes_table(tmp_path: Path) -> None:
    dataset_dir = _write_dataset(tmp_path / "ds")
    good = _write_jsonl(tmp_path / "good.jsonl", _GOOD)
    worse = _write_jsonl(tmp_path / "worse.jsonl", _WORSE)
    output = tmp_path / "out" / "comparison.md"

    exit_code = main(
        [
            "compare",
            "--dataset",
            str(dataset_dir),
            "--evaluations",
            f"good={good}",
            "--evaluations",
            f"worse={worse}",
            "--output",
            str(output),
            "--created-at",
            "2026-07-14T00:00:00Z",
            "--k",
            "1",
        ]
    )

    assert exit_code == 0
    table = output.read_text(encoding="utf-8")
    assert "good" in table and "worse" in table
    assert "recall@1" in table


def test_dataset_helper_builds_valid_dataset(tmp_path: Path) -> None:
    dataset = load_dataset(_write_dataset(tmp_path / "ds"))
    assert isinstance(dataset, GoldenDataset)
    assert [q.id for q in dataset.queries] == ["q1", "q2"]


def test_capture_cli_never_overwrites_recordings(tmp_path: Path) -> None:
    output = tmp_path / "capture.jsonl"
    output.write_text("existing", encoding="utf-8")
    result = main(
        [
            "capture",
            "--dataset",
            "missing",
            "--manifest",
            "missing",
            "--base-url",
            "http://localhost:8000",
            "--output",
            str(output),
        ]
    )
    assert result == 1
    assert output.read_text(encoding="utf-8") == "existing"


def test_capture_cli_rejects_insecure_remote_url(tmp_path: Path) -> None:
    result = main(
        [
            "capture",
            "--dataset",
            "missing",
            "--manifest",
            "missing",
            "--base-url",
            "http://example.com",
            "--output",
            str(tmp_path / "capture.jsonl"),
        ]
    )
    assert result == 1
