import httpx

from flint_graph.cli.corpus import main


def test_download_cli_rejects_invalid_budget_before_network(tmp_path, capsys):
    seen = []
    result = main(
        ["download", "--output", str(tmp_path / "reports"), "--max-source-bytes", "1", "--json"],
        transport=httpx.MockTransport(lambda request: seen.append(request)),
    )
    assert result == 1
    assert not seen
    assert '"status": "failed"' in capsys.readouterr().out


def test_download_cli_uses_only_fixed_pinned_sources_and_redacts_http_failure(tmp_path, capsys):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(403, content=b"secret credential and report payload")

    result = main(
        ["download", "--output", str(tmp_path / "reports"), "--json"],
        transport=httpx.MockTransport(handler),
    )
    assert result == 1
    assert seen == [
        "https://raw.githubusercontent.com/czyssrs/FinQA/"
        "0f16e2867befa6840783e58be38c9efb9229d742/LICENSE"
    ]
    assert "secret" not in capsys.readouterr().out


def test_verify_cli_requires_complete_artifacts_and_does_not_download(tmp_path, capsys):
    result = main(
        ["verify", "--directory", str(tmp_path), "--json"],
        transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(AssertionError())),
    )
    assert result == 1
    assert "manifest" in capsys.readouterr().out
