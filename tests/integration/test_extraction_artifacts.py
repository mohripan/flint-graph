import json
from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.chunking import ChunkingConfig, chunk_normalized_document
from atlas_rag.application.parsing import (
    NormalizedDocument,
    NormalizedElement,
    SourceFormat,
    SourceReference,
)
from atlas_rag.application.services.extraction import (
    ExtractionServiceConfig,
    persist_extraction_artifact,
)
from atlas_rag.application.services.intake import create_upload_intake
from atlas_rag.application.services.tenants import create_tenant
from atlas_rag.infrastructure.db.models import DocumentArtifact
from atlas_rag.infrastructure.object_store import ObjectInfo


class FakeObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.metadata: dict[str, dict[str, str]] = {}
        self.content_types: dict[str, str] = {}

    async def put_bytes(
        self,
        uri: str,
        data: bytes,
        *,
        content_type: str,
        metadata: Mapping[str, str] | None = None,
    ) -> None:
        self.objects[uri] = data
        self.content_types[uri] = content_type
        self.metadata[uri] = dict(metadata or {})

    async def get_bytes(self, uri: str) -> bytes:
        return self.objects[uri]

    async def head_object(self, uri: str) -> ObjectInfo:
        return ObjectInfo(
            size_bytes=len(self.objects[uri]),
            content_type=self.content_types[uri],
            metadata=self.metadata[uri],
        )


class FakeExtractionClient:
    def __init__(self, response: str | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.prompts: list[str] = []

    async def extract(
        self,
        *,
        prompt: str,
        model: str,
        timeout_seconds: int,
    ) -> str:
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


async def test_persist_extraction_artifact_records_success_provenance(
    db_session: AsyncSession,
) -> None:
    store = FakeObjectStore()
    tenant_id, normalized = await _create_normalized_document(db_session, store=store)
    manifest = chunk_normalized_document(
        normalized,
        config=ChunkingConfig(max_chunk_chars=200, overlap_chars=24),
    )
    client = FakeExtractionClient(
        response=json.dumps(
            {
                "title": "Extraction Source",
                "summary": "AtlasRAG extracts structured facts.",
                "topics": ["extraction", "lineage"],
                "entities": [{"name": "AtlasRAG", "type": "concept"}],
            }
        )
    )

    result = await persist_extraction_artifact(
        db_session,
        object_store=store,
        bucket="atlas-rag",
        tenant_id=tenant_id,
        document_id=normalized.source.document_id,
        version_id=normalized.source.document_version_id,
        chunk_manifest=manifest,
        config=ExtractionServiceConfig(mode="optional", model="gemma3:1b"),
        client=client,
    )

    artifact = await db_session.scalar(select(DocumentArtifact))
    assert artifact is not None
    assert result.status == "succeeded"
    assert result.blocks_version_activation is False
    assert artifact.artifact_type == "extraction"
    assert artifact.object_uri == result.extraction_artifact_uri
    assert artifact.content_hash.startswith("sha256:")
    assert artifact.metadata_["status"] == "succeeded"
    assert artifact.metadata_["provider"] == "ollama"
    assert artifact.metadata_["model"] == "gemma3:1b"
    assert artifact.metadata_["input_manifest_hash"].startswith("sha256:")
    assert artifact.metadata_["response_hash"].startswith("sha256:")
    assert store.content_types[artifact.object_uri] == "application/json"

    payload = json.loads(store.objects[artifact.object_uri])
    assert payload["schema_version"] == "2"
    assert payload["status"] == "succeeded"
    assert payload["extraction"]["summary"] == "AtlasRAG extracts structured facts."
    assert payload["provenance"]["prompt_version"] == "builtin-graph-v2"
    assert client.prompts and "chunk-000001" in client.prompts[0]


async def test_optional_extraction_failure_records_non_blocking_failure_artifact(
    db_session: AsyncSession,
) -> None:
    store = FakeObjectStore()
    tenant_id, normalized = await _create_normalized_document(db_session, store=store)
    manifest = chunk_normalized_document(
        normalized,
        config=ChunkingConfig(max_chunk_chars=200, overlap_chars=24),
    )

    result = await persist_extraction_artifact(
        db_session,
        object_store=store,
        bucket="atlas-rag",
        tenant_id=tenant_id,
        document_id=normalized.source.document_id,
        version_id=normalized.source.document_version_id,
        chunk_manifest=manifest,
        config=ExtractionServiceConfig(mode="optional", model="gemma3:1b"),
        client=FakeExtractionClient(error=RuntimeError("ollama unavailable")),
    )

    artifact = await db_session.scalar(select(DocumentArtifact))
    assert artifact is not None
    assert result.status == "failed"
    assert result.blocks_version_activation is False
    assert artifact.metadata_["status"] == "failed"
    assert artifact.metadata_["error_code"] == "extraction_failed"
    assert artifact.metadata_["error_message"] == "ollama unavailable"

    payload = json.loads(store.objects[artifact.object_uri])
    assert payload["status"] == "failed"
    assert payload["extraction"] is None
    assert payload["provenance"]["error_message"] == "ollama unavailable"


async def test_required_extraction_failure_is_recorded_as_blocking(
    db_session: AsyncSession,
) -> None:
    store = FakeObjectStore()
    tenant_id, normalized = await _create_normalized_document(db_session, store=store)
    manifest = chunk_normalized_document(
        normalized,
        config=ChunkingConfig(max_chunk_chars=200, overlap_chars=24),
    )

    result = await persist_extraction_artifact(
        db_session,
        object_store=store,
        bucket="atlas-rag",
        tenant_id=tenant_id,
        document_id=normalized.source.document_id,
        version_id=normalized.source.document_version_id,
        chunk_manifest=manifest,
        config=ExtractionServiceConfig(mode="required", model="gemma3:1b"),
        client=FakeExtractionClient(error=RuntimeError("bad response")),
    )

    artifact = await db_session.scalar(select(DocumentArtifact))
    assert artifact is not None
    assert result.status == "failed"
    assert result.blocks_version_activation is True
    assert artifact.metadata_["status"] == "failed"


async def test_disabled_extraction_records_skipped_artifact_without_calling_client(
    db_session: AsyncSession,
) -> None:
    store = FakeObjectStore()
    tenant_id, normalized = await _create_normalized_document(db_session, store=store)
    manifest = chunk_normalized_document(
        normalized,
        config=ChunkingConfig(max_chunk_chars=200, overlap_chars=24),
    )
    client = FakeExtractionClient(error=AssertionError("client should not be called"))

    result = await persist_extraction_artifact(
        db_session,
        object_store=store,
        bucket="atlas-rag",
        tenant_id=tenant_id,
        document_id=normalized.source.document_id,
        version_id=normalized.source.document_version_id,
        chunk_manifest=manifest,
        config=ExtractionServiceConfig(enabled=False, mode="optional", model="gemma3:1b"),
        client=client,
    )

    artifact = await db_session.scalar(select(DocumentArtifact))
    assert artifact is not None
    assert result.status == "skipped"
    assert result.blocks_version_activation is False
    assert client.prompts == []
    assert artifact.metadata_["status"] == "skipped"

    payload = json.loads(store.objects[artifact.object_uri])
    assert payload["status"] == "skipped"
    assert payload["extraction"] is None


async def _create_normalized_document(
    session: AsyncSession,
    *,
    store: FakeObjectStore,
) -> tuple[UUID, NormalizedDocument]:
    tenant = await create_tenant(session, name="Extraction Tenant")
    intake = await create_upload_intake(
        session,
        object_store=store,
        bucket="atlas-rag",
        tenant_id=tenant.id,
        title="Extraction Source",
        external_id="extraction-source",
        idempotency_key="extraction-source-v1",
        data=b"# Extraction Source\n\nAtlasRAG extracts structured facts.",
        content_type="text/markdown",
        original_filename="extraction.md",
    )
    content_hash = intake.version.content_hash
    assert content_hash is not None
    source = SourceReference(
        document_id=intake.document.id,
        document_version_id=intake.version.id,
        content_hash=content_hash,
    )
    return (
        tenant.id,
        NormalizedDocument(
            source=source,
            format=SourceFormat.MARKDOWN,
            title="Extraction Source",
            elements=[
                NormalizedElement(
                    id="element-000001",
                    type="heading",
                    text="Extraction Source",
                    level=1,
                ),
                NormalizedElement(
                    id="element-000002",
                    type="paragraph",
                    text="AtlasRAG extracts structured facts.",
                ),
            ],
        ),
    )
