import hashlib
import json

import httpx
import pytest

from flint_graph.evaluation.financial_corpus import (
    CorpusError,
    CorpusSource,
    collect_financial_corpus,
    export_financial_dataset,
    render_report_excerpt,
    verify_financial_corpus,
)


def test_report_evidence_renders_only_source_text_and_table_not_answer_annotations():
    record = {
        "id": "ACME/2018/page_42.pdf-2",
        "pre_text": ["Revenue increased in 2018."],
        "post_text": ["Amounts in millions."],
        "table": [["Year", "Revenue"], ["2018", "$500 | unaudited"]],
        "qa": {"question": "SECRET QUESTION", "answer": "SECRET GOLD"},
        "model_input": "SECRET MODEL INPUT",
    }
    excerpt = render_report_excerpt(record)
    assert excerpt.company == "ACME"
    assert excerpt.year == 2018
    assert excerpt.page == 42
    assert "Revenue increased in 2018." in excerpt.text
    assert "$500 \\| unaudited" in excerpt.text
    assert "Amounts in millions." in excerpt.text
    assert "SECRET" not in excerpt.text
    assert "excerpt" in excerpt.text.lower()


def fixture_record(suffix="1", text="Reported revenue."):
    return {
        "id": f"ACME/2018/page_42.pdf-{suffix}",
        "pre_text": [text],
        "post_text": ["Amounts in millions."],
        "table": [["Year", "Revenue"], ["2018", "$500"]],
        "qa": {"question": "SECRET QUESTION", "answer": "SECRET GOLD", "exe_ans": 500},
    }


def fixture_sources():
    payloads = {
        "LICENSE": b"MIT fixture attribution",
        "dataset/dev.json": json.dumps([fixture_record(), fixture_record("2")]).encode(),
        "dataset/test.json": json.dumps(
            [fixture_record("3", "Different report context.")]
        ).encode(),
    }
    sources = tuple(
        CorpusSource(
            path=path,
            size=len(payload),
            git_blob_sha1=hashlib.sha1(
                f"blob {len(payload)}\0".encode() + payload, usedforsecurity=False
            ).hexdigest(),
        )
        for path, payload in payloads.items()
    )
    return payloads, sources


async def test_collection_deduplicates_evidence_preserves_provenance_and_separates_gold(tmp_path):
    payloads, sources = fixture_sources()
    seen = []

    def handler(request):
        assert request.url.host == "raw.githubusercontent.com"
        assert not request.headers.get("authorization")
        path = str(request.url).split("0f16e2867befa6840783e58be38c9efb9229d742/")[1]
        seen.append(path)
        return httpx.Response(200, content=payloads[path])

    output = tmp_path / "reports"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        manifest = await collect_financial_corpus(client, output, sources=sources)
    assert sorted(seen) == sorted(payloads)
    assert manifest["example_count"] == 3
    assert manifest["document_count"] == 2
    assert manifest["report_count"] == 1
    documents = manifest["documents"]
    assert sorted(len(item["examples"]) for item in documents) == [1, 2]
    assert all("SECRET" not in (output / item["path"]).read_text() for item in documents)
    assert "SECRET GOLD" in (output / "annotations.jsonl").read_text()
    assert not list((output / "corpus").glob("*.json*"))
    assert verify_financial_corpus(output, sources=sources)["document_count"] == 2
    for source in manifest["sources"]:
        assert source["sha256"] == hashlib.sha256(payloads[source["source_path"]]).hexdigest()


async def test_collection_refuses_existing_directory_without_network_or_overwrite(tmp_path):
    seen = []
    marker = tmp_path / "mine.txt"
    marker.write_text("preserve me")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: seen.append(request))
    ) as client:
        with pytest.raises(CorpusError, match="new directory"):
            await collect_financial_corpus(client, tmp_path)
    assert not seen
    assert marker.read_text() == "preserve me"


@pytest.mark.parametrize("failure", ["redirect", "corrupt", "oversized", "length"])
async def test_collection_rejects_redirects_corruption_and_excess_bytes(tmp_path, failure):
    payloads, sources = fixture_sources()

    def handler(request):
        path = str(request.url).split("0f16e2867befa6840783e58be38c9efb9229d742/")[1]
        body = payloads[path]
        if failure == "redirect":
            return httpx.Response(302, headers={"location": "https://evil.example/private"})
        if failure == "corrupt":
            body = b"x" * len(body)
        if failure == "oversized":
            body += b"x"
        headers = {"content-length": "999999999"} if failure == "length" else {}
        return httpx.Response(200, content=body, headers=headers)

    output = tmp_path / "reports"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CorpusError):
            await collect_financial_corpus(client, output, sources=sources)
    assert not (output / "manifest.json").exists()


async def test_collection_preflights_budget_before_download(tmp_path):
    _, sources = fixture_sources()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: pytest.fail())
    ) as client:
        with pytest.raises(CorpusError, match="budget"):
            await collect_financial_corpus(
                client, tmp_path / "reports", sources=sources, max_bytes=1
            )


async def test_verify_rejects_tampering_and_paths_outside_artifact_directory(tmp_path):
    payloads, sources = fixture_sources()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=payloads[
                    str(request.url).split("0f16e2867befa6840783e58be38c9efb9229d742/")[1]
                ],
            )
        )
    ) as client:
        await collect_financial_corpus(client, tmp_path / "reports", sources=sources)
    output = tmp_path / "reports"
    manifest = json.loads((output / "manifest.json").read_text())
    path = output / manifest["documents"][0]["path"]
    path.write_text("tampered")
    with pytest.raises(CorpusError, match="checksum"):
        verify_financial_corpus(output, sources=sources)
    manifest["files"][0]["path"] = "../outside.txt"
    (output / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(CorpusError, match="path"):
        verify_financial_corpus(output, sources=sources)


@pytest.mark.parametrize("identity", ["../../etc/passwd", "ACME/2018/../../gold.pdf-1", ""])
def test_excerpt_rejects_unsafe_report_identity(identity):
    record = fixture_record()
    record["id"] = identity
    with pytest.raises(CorpusError, match="identity"):
        render_report_excerpt(record)


async def test_export_creates_bounded_evidence_only_dataset_without_answer_annotations(tmp_path):
    from flint_graph.evaluation.datasets import load_dataset
    from flint_graph.evaluation.prepare import load_corpus

    payloads, sources = fixture_sources()

    def handler(request):
        path = str(request.url).split("0f16e2867befa6840783e58be38c9efb9229d742/")[1]
        return httpx.Response(200, content=payloads[path])

    root = tmp_path / "reports"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await collect_financial_corpus(client, root, sources=sources)
    output = tmp_path / "batch"
    result = export_financial_dataset(root, output, max_documents=1, sources=sources)
    assert result["document_count"] == 1
    dataset = load_dataset(output)
    corpus = load_corpus(output, dataset)
    assert len(corpus) == 1
    assert not dataset.queries
    assert b"SECRET" not in corpus[0].content
    assert not (output / "annotations.jsonl").exists()
    assert (output / "LICENSE").is_file()
    assert (output / "ATTRIBUTION.txt").is_file()
    with pytest.raises(CorpusError, match="new directory"):
        export_financial_dataset(root, output, sources=sources)
    with pytest.raises(CorpusError, match="batch"):
        export_financial_dataset(root, tmp_path / "too-many", max_documents=101, sources=sources)


async def test_truncated_collection_reports_selected_count_not_full_corpus(tmp_path):
    payloads, sources = fixture_sources()

    def handler(request):
        path = str(request.url).split("0f16e2867befa6840783e58be38c9efb9229d742/")[1]
        return httpx.Response(200, content=payloads[path])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        manifest = await collect_financial_corpus(
            client, tmp_path / "reports", sources=sources, max_documents=1
        )
    assert manifest["document_count"] == 1
    assert manifest["example_count"] == 2
    assert manifest["available_example_count"] == 3
    assert manifest["truncated"] is True


async def test_verify_cannot_be_tricked_into_uploading_gold_by_rewriting_manifest_hashes(tmp_path):
    payloads, sources = fixture_sources()

    def handler(request):
        path = str(request.url).split("0f16e2867befa6840783e58be38c9efb9229d742/")[1]
        return httpx.Response(200, content=payloads[path])

    root = tmp_path / "reports"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        manifest = await collect_financial_corpus(client, root, sources=sources)
    document = manifest["documents"][0]
    bad = b"SECRET GOLD"
    (root / document["path"]).write_bytes(bad)
    document.update(bytes=len(bad), sha256=hashlib.sha256(bad).hexdigest())
    for item in manifest["files"]:
        if item["path"] == document["path"]:
            item.update(bytes=len(bad), sha256=hashlib.sha256(bad).hexdigest())
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(CorpusError, match="source evidence"):
        verify_financial_corpus(root, sources=sources)
