from flint_graph.cli.eval import main


def test_nightly_cli_refuses_existing_report_without_touching_it(tmp_path, capsys):
    output = tmp_path / "report.json"
    output.write_text("KEEP", encoding="utf-8")
    result = main(
        [
            "nightly",
            "--dataset",
            "missing",
            "--manifest",
            "missing",
            "--corpus",
            "missing",
            "--base-url",
            "http://localhost:8000",
            "--isolation-workspace-id",
            "11111111-1111-1111-1111-111111111111",
            "--inspect",
            "--output",
            str(output),
        ]
    )
    assert result == 1 and output.read_text() == "KEEP"
    assert "already exists" in capsys.readouterr().out
