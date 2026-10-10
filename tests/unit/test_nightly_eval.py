import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from flint_graph.evaluation.capture import CaptureManifest
from flint_graph.evaluation.datasets import DatasetMetadata, GoldenDataset, GoldenQuery
from flint_graph.evaluation.nightly import (
    AnswerRubric,
    NightlyError,
    NightlyPolicy,
    inspect_nightly_target,
    matches_rubric,
    run_nightly,
)


@pytest.mark.parametrize(
    "case,answer,expected",
    [
        ("pm-rrp-2017", "Net revenues for RRPs were $3.6 billion.", True),
        ("pm-rrp-2016", "Net revenues for RRPs were $733 million.", True),
        ("pm-rrp-2017", "RRP net revenues were 3600 million.", True),
        ("pm-rrp-2017", "Reduced-risk net revenues were 3.6 billion.", True),
        ("pm-rrp-2017", "RRPs net revenues were 3.8 billion.", False),
        ("pm-rrp-2017", "RRPs net revenues were 3.6 million.", False),
        ("pm-rrp-2017", "RRPs net revenues were 733 million.", False),
        ("pm-rrp-2016", "RRPs net revenues were 739 million.", False),
        ("pm-rrp-2016", "RRPs net revenues were 733 billion.", False),
        ("pm-rrp-2017", "RRPsomething net revenues were 3.6 billion.", False),
        ("pm-rrp-2017", "AnotherRRP net revenues were 3.6 billion.", False),
        ("amex-average", "American Express average was $127400.", False),
    ],
)
def test_checked_in_financial_rubrics_preserve_concept_value_and_unit_boundaries(
    case, answer, expected
):
    path = Path(__file__).parents[2] / "evals/datasets/financial-nightly/rubrics.json"
    rubric = AnswerRubric.model_validate(json.loads(path.read_text(encoding="utf-8"))[case])
    assert matches_rubric(rubric, answer) is expected


@pytest.mark.parametrize(
    "answer,expected",
    [
        ("Operating income was $11,503 million.", True),
        ("Operating income was 11503 million dollars.", True),
        ("Operating income was $11.503 billion.", True),
        ("Operating income was $11,503 billion.", False),
        ("Operating income was $10,815 million.", False),
        ("Revenue was $11,503 million.", False),
    ],
)
def test_source_reviewed_rubric_accepts_equivalent_numbers_but_not_wrong_units_or_concepts(
    answer,
    expected,
):
    rubric = AnswerRubric(
        groups=[
            ["operating income"],
            ["11503 million", "11.503 billion"],
        ]
    )
    assert matches_rubric(rubric, answer) is expected


def fixture_target(*, provider="ollama", isolation_status=404, answer="Revenue was $500 million."):
    tenant, isolation, document, version, index = (str(uuid4()) for _ in range(5))
    label = "finqa-" + "a" * 64
    manifest = CaptureManifest(
        tenant_id=tenant,
        dataset_name="mini",
        dataset_version=1,
        document_labels={document: label},
        preparation={"document_versions": {version: document}},
    )
    dataset = GoldenDataset(
        metadata=DatasetMetadata(name="mini", version=1, tenant="public-financial"),
        queries=[
            GoldenQuery(
                id="revenue",
                query="What was reported revenue in millions?",
                query_type="factoid",
                relevant_chunk_ids=[label],
                must_cite_sources=[label],
            )
        ],
    )
    rubrics = {"revenue": AnswerRubric(groups=[["revenue"], ["500 million"]])}
    models = [
        {
            "role": "embedding",
            "provider": "deterministic",
            "model": "fixture",
            "status": "offline",
            "digest": None,
        },
        {
            "role": "answer",
            "provider": provider,
            "model": "test:fixed",
            "status": "available",
            "digest": "sha256:" + "b" * 64,
        },
        {
            "role": "support",
            "provider": provider,
            "model": "test:fixed",
            "status": "available",
            "digest": "sha256:" + "b" * 64,
        },
    ]
    seen = []

    def handler(request):
        path = request.url.path
        seen.append((request.method, path))
        if path == "/v1/workspaces":
            return httpx.Response(200, json=[{"id": tenant}, {"id": isolation}])
        if path == "/v1/system-readiness":
            return httpx.Response(
                200,
                json={
                    "setup_capabilities": {"query_usage_rollups": True},
                    "search_readiness": {"ready": True, "active_index_version": {"id": index}},
                },
            )
        if path == "/v1/model-readiness":
            return httpx.Response(200, json=models)
        if path == "/v1/documents":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": document,
                        "title": label,
                        "latest_version_id": version,
                        "latest_version_status": "active",
                    }
                ],
            )
        if path == "/v1/query-runs" and request.method == "POST":
            return httpx.Response(201, json={"id": str(uuid4())})
        if request.headers.get("X-Tenant-ID") == isolation:
            return httpx.Response(isolation_status, json={"detail": "SECRET FOREIGN PAYLOAD"})
        if path.endswith("/events/stream"):
            return httpx.Response(200, text="event: query.completed\ndata: {}\n\n")
        if path.endswith("/retrieval"):
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "candidate_id": "c1",
                            "candidate_type": "chunk",
                            "rerank_rank": 1,
                            "document_id": document,
                            "source_ids": {"chunk_id": "chunk-1"},
                        }
                    ]
                },
            )
        if path.endswith("/provenance"):
            return httpx.Response(
                200,
                json={
                    "answer_text": answer,
                    "abstained": False,
                    "answer_citations": [{"citation_id": "c1"}],
                    "claims": [{"support_status": "supported"}],
                    "citations": [
                        {
                            "citation_id": "c1",
                            "source_document_id": document,
                            "source_ids": {"chunk_id": "chunk-1"},
                            "source_active": True,
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "retrieval_index_version_id": index,
                "provider_input_tokens": 100,
                "provider_output_tokens": 20,
            },
        )

    return dataset, manifest, isolation, label, rubrics, models, seen, handler


async def test_fresh_nightly_run_is_serialized_redacted_and_uses_real_usage_and_isolation():
    dataset, manifest, isolation, label, rubrics, _, seen, handler = fixture_target()
    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    ) as client:
        snapshot = await inspect_nightly_target(
            client, manifest, approved_labels={label}, isolation_workspace_id=isolation
        )
        assert not any(method == "POST" for method, _ in seen)
        result = await run_nightly(
            client,
            dataset,
            manifest,
            rubrics,
            approved_labels={label},
            isolation_workspace_id=isolation,
            expected_model_fingerprint=snapshot["model_fingerprint"],
            policy=NightlyPolicy(),
        )
    assert result["status"] == "passed"
    assert result["query_count"] == 1
    assert result["input_tokens"] == 100 and result["output_tokens"] == 20
    assert result["tenant_isolation_passed"] is True
    assert result["aggregate"]["useful_answer_rate"] == 1
    assert result["cost_status"] == "unpriced_local_compute"
    assert result["estimated_cost_usd"] is None
    assert result["format_version"] == 2
    assert result["dataset_name"] == dataset.metadata.name
    assert result["dataset_version"] == dataset.metadata.version
    assert len(result["rubric_fingerprint"]) == 64
    assert len(result["policy_fingerprint"]) == 64
    serialized = json.dumps(result)
    assert "SECRET" not in serialized and "Revenue was" not in serialized
    assert "What was" not in serialized and "http://test" not in serialized
    assert sum(method == "POST" and path == "/v1/query-runs" for method, path in seen) == 1


async def test_report_fingerprints_track_rubric_and_policy_without_reversioning_corpus():
    dataset, manifest, isolation, label, rubrics, _, _, handler = fixture_target()
    dataset = dataset.model_copy(
        update={
            "queries": [dataset.queries[0], dataset.queries[0].model_copy(update={"id": "second"})]
        }
    )
    rubrics["second"] = rubrics["revenue"]
    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    ) as client:
        snapshot = await inspect_nightly_target(
            client, manifest, approved_labels={label}, isolation_workspace_id=isolation
        )

        async def capture(selected_rubrics, policy):
            return await run_nightly(
                client,
                dataset,
                manifest,
                selected_rubrics,
                approved_labels={label},
                isolation_workspace_id=isolation,
                expected_model_fingerprint=snapshot["model_fingerprint"],
                policy=policy,
            )

        original = await capture(rubrics, NightlyPolicy())
        same = await capture(dict(reversed(list(rubrics.items()))), NightlyPolicy())
        alias = await capture(
            {
                **rubrics,
                "revenue": AnswerRubric(groups=[["revenue", "revenues"], ["500 million"]]),
            },
            NightlyPolicy(),
        )
        policy_change = await capture(rubrics, NightlyPolicy(max_queries=15))
    assert original["rubric_fingerprint"] == same["rubric_fingerprint"]
    assert original["rubric_fingerprint"] != alias["rubric_fingerprint"]
    assert original["policy_fingerprint"] == alias["policy_fingerprint"]
    assert original["policy_fingerprint"] != policy_change["policy_fingerprint"]
    assert original["corpus_fingerprint"] == alias["corpus_fingerprint"]
    assert original["dataset_version"] == alias["dataset_version"] == 1


@pytest.mark.parametrize("provider", ["anthropic", "openai", "deterministic"])
async def test_nightly_refuses_hosted_and_fixture_answer_providers_before_queries(provider):
    _, manifest, isolation, label, _, _, seen, handler = fixture_target(provider=provider)
    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(NightlyError, match="Ollama"):
            await inspect_nightly_target(
                client, manifest, approved_labels={label}, isolation_workspace_id=isolation
            )
    assert not any(method == "POST" for method, _ in seen)


@pytest.mark.parametrize("failure", ["fingerprint", "tokens", "isolation", "quality"])
async def test_nightly_never_labels_failed_or_over_budget_runs_as_quality_passes(failure):
    dataset, manifest, isolation, label, rubrics, _, seen, handler = fixture_target(
        isolation_status=200 if failure == "isolation" else 404,
        answer="Wrong or unsupported final answer"
        if failure == "quality"
        else "Revenue was $500 million.",
    )
    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    ) as client:
        snapshot = await inspect_nightly_target(
            client, manifest, approved_labels={label}, isolation_workspace_id=isolation
        )
        result = await run_nightly(
            client,
            dataset,
            manifest,
            rubrics,
            approved_labels={label},
            isolation_workspace_id=isolation,
            expected_model_fingerprint="wrong"
            if failure == "fingerprint"
            else snapshot["model_fingerprint"],
            policy=NightlyPolicy(max_provider_tokens=1 if failure == "tokens" else 100000),
        )
    assert result["status"] == "failed"
    if failure == "quality":
        assert result["usage_complete"] is True
    if failure == "fingerprint":
        assert not any(method == "POST" for method, _ in seen)
    assert "SECRET" not in json.dumps(result)


async def test_failed_second_query_retains_partial_metrics_and_incomplete_usage():
    dataset, manifest, isolation, label, rubrics, _, _, handler = fixture_target()
    dataset = dataset.model_copy(
        update={
            "queries": [dataset.queries[0], dataset.queries[0].model_copy(update={"id": "second"})]
        }
    )
    rubrics["second"] = rubrics["revenue"]
    creates = 0

    def changed(request):
        nonlocal creates
        if request.method == "POST":
            creates += 1
            if creates == 2:
                return httpx.Response(500, json={"detail": "SECRET PROVIDER PAYLOAD"})
        return handler(request)

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(changed)
    ) as client:
        snapshot = await inspect_nightly_target(
            client, manifest, approved_labels={label}, isolation_workspace_id=isolation
        )
        result = await run_nightly(
            client,
            dataset,
            manifest,
            rubrics,
            approved_labels={label},
            isolation_workspace_id=isolation,
            expected_model_fingerprint=snapshot["model_fingerprint"],
            policy=NightlyPolicy(),
        )
    assert result["status"] == "failed" and result["query_count"] == 1
    assert result["attempted_query_count"] == 2 and result["planned_query_count"] == 2
    assert result["usage_complete"] is False
    assert result["aggregate"]["useful_answer_rate"] == 1
    assert "SECRET" not in json.dumps(result)


@pytest.mark.parametrize("change", ["extra_document", "version", "missing_usage", "drift"])
async def test_nightly_rejects_changed_corpus_missing_usage_and_mid_run_model_drift(change):
    dataset, manifest, isolation, label, rubrics, models, seen, handler = fixture_target()
    model_reads = 0

    def changed(request):
        nonlocal model_reads
        response = handler(request)
        if request.url.path == "/v1/documents":
            rows = response.json()
            if change == "extra_document":
                rows.append({"id": str(uuid4()), "title": "PRIVATE"})
            elif change == "version":
                rows[0]["latest_version_id"] = str(uuid4())
            return httpx.Response(200, json=rows)
        if request.url.path == "/v1/model-readiness":
            model_reads += 1
            if change == "drift" and model_reads > 2:
                return httpx.Response(
                    200, json=[dict(row, digest="sha256:" + "c" * 64) for row in models]
                )
        if (
            change == "missing_usage"
            and request.url.path.startswith("/v1/query-runs/")
            and request.url.path.count("/") == 3
            and request.headers.get("X-Tenant-ID") != isolation
        ):
            return httpx.Response(
                200, json={"status": "completed", "retrieval_index_version_id": str(uuid4())}
            )
        return response

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(changed)
    ) as client:
        if change in {"extra_document", "version"}:
            with pytest.raises(NightlyError):
                await inspect_nightly_target(
                    client, manifest, approved_labels={label}, isolation_workspace_id=isolation
                )
            assert not any(method == "POST" for method, _ in seen)
        else:
            snapshot = await inspect_nightly_target(
                client, manifest, approved_labels={label}, isolation_workspace_id=isolation
            )
            result = await run_nightly(
                client,
                dataset,
                manifest,
                rubrics,
                approved_labels={label},
                isolation_workspace_id=isolation,
                expected_model_fingerprint=snapshot["model_fingerprint"],
                policy=NightlyPolicy(),
            )
            assert result["status"] == "failed"


async def test_token_stop_does_not_issue_the_next_fresh_query():
    dataset, manifest, isolation, label, rubrics, _, seen, handler = fixture_target()
    second = dataset.queries[0].model_copy(update={"id": "second"})
    dataset = dataset.model_copy(update={"queries": [*dataset.queries, second]})
    rubrics["second"] = rubrics["revenue"]
    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    ) as client:
        snapshot = await inspect_nightly_target(
            client, manifest, approved_labels={label}, isolation_workspace_id=isolation
        )
        result = await run_nightly(
            client,
            dataset,
            manifest,
            rubrics,
            approved_labels={label},
            isolation_workspace_id=isolation,
            expected_model_fingerprint=snapshot["model_fingerprint"],
            policy=NightlyPolicy(max_provider_tokens=1),
        )
    assert result["status"] == "failed" and result["query_count"] == 1
    assert sum(method == "POST" for method, _ in seen) == 1


async def test_correct_literal_answer_without_supported_claims_cannot_pass():
    dataset, manifest, isolation, label, rubrics, _, _, handler = fixture_target()

    def changed(request):
        response = handler(request)
        if (
            request.url.path.endswith("/provenance")
            and request.headers.get("X-Tenant-ID") != isolation
        ):
            payload = response.json()
            payload["claims"] = []
            return httpx.Response(200, json=payload)
        return response

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(changed)
    ) as client:
        snapshot = await inspect_nightly_target(
            client, manifest, approved_labels={label}, isolation_workspace_id=isolation
        )
        result = await run_nightly(
            client,
            dataset,
            manifest,
            rubrics,
            approved_labels={label},
            isolation_workspace_id=isolation,
            expected_model_fingerprint=snapshot["model_fingerprint"],
            policy=NightlyPolicy(min_useful_answer_rate=0),
        )
    assert result["status"] == "failed"
