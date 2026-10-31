"""Admission pins a durable bundle; a later label/deploy cannot change a queued turn."""

from uuid import UUID, uuid4

import pytest
from test_narrative_assistant_execution import environment
from test_narrative_assistant_execution import turn_case as turn_case

from flint_graph.application.services.narrative_assistant import register_turn_workflow
from flint_graph.narrative.assistant.turn import ModelReply
from flint_graph.prompts.catalog import PromptEntry
from flint_graph.prompts.source import PromptBundle, current_snapshot, use_snapshot
from flint_graph.worker.activities.narrative_assistant import NarrativeAssistantActivities


@pytest.mark.anyio
async def test_queued_turn_uses_admission_bundle_after_active_bundle_changes(turn_case):
    factory, ask, _ = turn_case
    original = current_snapshot()
    payload = await ask()
    run_id = uuid4()
    async with factory() as session:
        await register_turn_workflow(
            session,
            tenant_id=UUID(payload["tenant_id"]),
            turn_id=UUID(payload["turn_id"]),
            workflow_run_id=run_id,
        )
        await session.commit()
    data = original.entry("narrative.assistant.system").data
    data.pop("type")
    data["catalog_version"] += 1
    data["template"][0]["content"] = "A later deployment must not affect this queued turn."
    replacement = PromptEntry.create(**data)
    later = PromptBundle.create(
        [replacement if e.name == replacement.name else e for e in original.entries],
        source_revision="fixture",
        evaluation_record="fixture",
    )

    class RecordingModel:
        provider = "scripted"

        def __init__(self):
            self.observed = []

        async def respond(self, messages, schema, on_delta=None):
            self.observed.append(messages[0]["content"])
            return ModelReply('{"reply":"A synthetic answer.","proposal":null}', "synthetic", 1, 1)

    model = RecordingModel()
    activities = NarrativeAssistantActivities(factory=factory, model=model, context_chars=24000)
    with use_snapshot(later):
        outcome = await environment(payload, run_id).run(activities.run, payload)
    assert outcome["status"] == "completed"
    assert model.observed == [
        original.entry("narrative.assistant.system").data["template"][0]["content"]
    ]


@pytest.mark.anyio
async def test_query_execution_uses_its_admission_bundle(extraction_db_session):
    from test_query_orchestration import FakeRetrievers, _query_run, _tenant

    from flint_graph.application.services.query_orchestration import (
        QueryRetrieverBundle,
        run_query_retrieval_graph,
    )

    original = current_snapshot()
    tenant = await _tenant(extraction_db_session, "snapshot-query")
    run_id, _ = await _query_run(extraction_db_session, tenant, "What is Acme?")
    later = PromptBundle.create(
        original.entries, source_revision="later-fixture", evaluation_record="fixture"
    )
    observed = []

    class RecordingRetrievers(FakeRetrievers):
        async def retrieve_lexical(self, session, **kwargs):
            observed.append(current_snapshot().sha256)
            return await super().retrieve_lexical(session, **kwargs)

    retrievers = RecordingRetrievers()
    with use_snapshot(later):
        await run_query_retrieval_graph(
            extraction_db_session,
            tenant_id=tenant.id,
            query_run_id=run_id,
            retrievers=QueryRetrieverBundle(
                lexical=retrievers, vector=retrievers, graph=retrievers
            ),
        )
    assert observed == [original.sha256]


@pytest.mark.anyio
async def test_corrupt_historical_bundle_stops_replay_instead_of_using_current(db_session):
    from flint_graph.application.services.prompt_bundles import load_bundle, pin_bundle
    from flint_graph.infrastructure.db.prompt_models import PromptBundleRecord
    from flint_graph.prompts.catalog import PromptError

    sha = await pin_bundle(db_session)
    row = await db_session.get(PromptBundleRecord, sha)
    manifest = row.manifest.copy()
    manifest["source_revision"] = "tampered"
    row.manifest = manifest
    await db_session.flush()
    with pytest.raises(PromptError, match="bundle_hash_mismatch"):
        await load_bundle(db_session, sha)


@pytest.mark.anyio
async def test_extraction_same_output_under_new_bundle_has_distinct_manifest(extraction_db_session):
    db_session = extraction_db_session
    from test_provenance_extraction_persistence import FakeObjectStore, _seed_document

    from flint_graph.application.extraction_proposals import ExtractionBatch, ExtractionInputChunk
    from flint_graph.application.services.provenance_extraction import (
        ProvenanceExtractionMetadata,
        persist_provenance_extraction_run,
    )

    tenant, document, version = await _seed_document(db_session)
    original = current_snapshot()
    data = original.entry("extraction.proposals.ollama").data
    data.pop("type")
    data["catalog_version"] += 1
    data["template"] += "\nA separately reviewed fixture instruction."
    changed_entry = PromptEntry.create(**data)
    changed = PromptBundle.create(
        [changed_entry if e.name == changed_entry.name else e for e in original.entries],
        source_revision="fixture",
        evaluation_record="fixture",
    )
    store = FakeObjectStore()
    results = []
    for bundle in [original, changed, changed]:
        with use_snapshot(bundle):
            results.append(
                await persist_provenance_extraction_run(
                    db_session,
                    object_store=store,
                    bucket="synthetic",
                    tenant_id=tenant.id,
                    document_id=document.id,
                    version_id=version.id,
                    chunks=[ExtractionInputChunk(chunk_id="synthetic", text="Synthetic input.")],
                    batch=ExtractionBatch(input_chunk_ids=["synthetic"]),
                    metadata=ProvenanceExtractionMetadata(
                        prompt_version="proposal-v1",
                        extractor_version="fixture",
                        model_provider="deterministic",
                        model_name="fixture",
                        request_hash="synthetic",
                    ),
                )
            )
    assert results[0].extraction_run_id != results[1].extraction_run_id
    assert results[0].manifest_hash != results[1].manifest_hash
    assert results[1] == results[2]


@pytest.mark.anyio
async def test_completed_legacy_run_does_not_acquire_a_fabricated_prompt_identity(db_session):
    from test_query_orchestration import _query_run, _tenant

    from flint_graph.application.services.prompt_bundles import execution_bundle
    from flint_graph.domain.enums import QueryRunStatus
    from flint_graph.infrastructure.db.models import QueryRun
    from flint_graph.prompts.catalog import PromptError

    tenant = await _tenant(db_session, "legacy-snapshot")
    run_id, _ = await _query_run(db_session, tenant, "Synthetic historic query")
    run = await db_session.get(QueryRun, run_id)
    run.prompt_bundle_sha256 = None
    run.status = QueryRunStatus.COMPLETED
    await db_session.flush()
    with pytest.raises(PromptError, match="historical_bundle_unavailable"):
        await execution_bundle(db_session, run)
    assert run.prompt_bundle_sha256 is None
