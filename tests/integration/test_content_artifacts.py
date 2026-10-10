import json
from collections.abc import Mapping
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.chunking import ChunkingConfig
from flint_graph.application.parsing import (
    NormalizedDocument,
    NormalizedElement,
    SourceFormat,
    SourceMetadata,
    SourceReference,
)
from flint_graph.application.parsing.parsers import parse_normalized_document
from flint_graph.application.services.content_artifacts import persist_content_artifacts
from flint_graph.application.services.intake import create_upload_intake
from flint_graph.application.services.tenants import create_tenant
from flint_graph.infrastructure.db.models import DocumentArtifact, DocumentChunk
from flint_graph.infrastructure.object_store import ObjectInfo


async def test_nul_normalized_text_persists_and_retains_raw_source_and_warning(
    extraction_db_session,
):
    session = extraction_db_session
    store = FakeObjectStore()
    tenant = await create_tenant(session, name="NUL parser regression")
    raw = b"Math\x00proof has exact evidence."
    intake = await create_upload_intake(
        session,
        object_store=store,
        bucket="flint-graph",
        tenant_id=tenant.id,
        title="NUL fixture",
        external_id="nul-fixture",
        idempotency_key="nul-fixture-v1",
        data=raw,
        content_type="text/plain",
        original_filename="nul.txt",
    )
    normalized = parse_normalized_document(
        raw,
        metadata=SourceMetadata(
            document_id=intake.document.id,
            document_version_id=intake.version.id,
            content_hash=intake.version.content_hash,
            content_type="text/plain",
        ),
    )
    result = await persist_content_artifacts(
        session,
        object_store=store,
        bucket="flint-graph",
        tenant_id=tenant.id,
        document_id=intake.document.id,
        version_id=intake.version.id,
        normalized_document=normalized,
        chunking_config=ChunkingConfig(max_chunk_chars=200, overlap_chars=0),
    )
    await session.flush()
    artifact = json.loads(await store.get_bytes(result.normalized_artifact_uri))
    assert artifact["elements"][0]["text"] == "Math\ufffdproof has exact evidence."
    assert artifact["warnings"] == ["nul_characters_replaced:1"]
    assert await store.get_bytes(intake.version.object_uri) == raw


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


async def test_persist_content_artifacts_writes_objects_and_queryable_chunk_lineage(
    db_session: AsyncSession,
) -> None:
    store = FakeObjectStore()
    tenant = await create_tenant(db_session, name="Content Artifacts Tenant")
    intake = await create_upload_intake(
        db_session,
        object_store=store,
        bucket="flint-graph",
        tenant_id=tenant.id,
        title="Artifact Source",
        external_id="artifact-source",
        idempotency_key="artifact-source-v1",
        data=b"# Artifact Source\n\nBody text for chunks.",
        content_type="text/markdown",
        original_filename="artifact.md",
    )
    content_hash = intake.version.content_hash
    assert content_hash is not None
    normalized = NormalizedDocument(
        source=SourceReference(
            document_id=intake.document.id,
            document_version_id=intake.version.id,
            content_hash=content_hash,
        ),
        format=SourceFormat.MARKDOWN,
        title="Artifact Source",
        elements=[
            NormalizedElement(id="element-000001", type="heading", text="Artifact Source", level=1),
            NormalizedElement(id="element-000002", type="paragraph", text="Body text for chunks."),
        ],
    )

    result = await persist_content_artifacts(
        db_session,
        object_store=store,
        bucket="flint-graph",
        tenant_id=tenant.id,
        document_id=intake.document.id,
        version_id=intake.version.id,
        normalized_document=normalized,
        chunking_config=ChunkingConfig(max_chunk_chars=200, overlap_chars=24),
    )

    artifacts = list(
        await db_session.scalars(select(DocumentArtifact).order_by(DocumentArtifact.artifact_type))
    )
    chunks = list(
        await db_session.scalars(select(DocumentChunk).order_by(DocumentChunk.chunk_index))
    )

    assert [artifact.artifact_type for artifact in artifacts] == ["chunk_manifest", "normalized"]
    assert len(chunks) == 1
    assert chunks[0].text == "Body text for chunks."
    assert chunks[0].chunk_index == 0
    assert chunks[0].chunk_hash == "sha256:" + sha256(b"Body text for chunks.").hexdigest()
    assert chunks[0].source_element_ids == ["element-000002"]
    assert chunks[0].heading_path == ["Artifact Source"]
    assert chunks[0].metadata_ == {"format": "markdown"}

    normalized_artifact = next(
        artifact for artifact in artifacts if artifact.artifact_type == "normalized"
    )
    manifest_artifact = next(
        artifact for artifact in artifacts if artifact.artifact_type == "chunk_manifest"
    )
    assert normalized_artifact.object_uri == result.normalized_artifact_uri
    assert manifest_artifact.object_uri == result.chunk_manifest_uri
    assert normalized_artifact.content_hash.startswith("sha256:")
    assert manifest_artifact.content_hash.startswith("sha256:")
    assert normalized_artifact.size_bytes == len(store.objects[normalized_artifact.object_uri])
    assert manifest_artifact.size_bytes == len(store.objects[manifest_artifact.object_uri])
    assert store.content_types[normalized_artifact.object_uri] == "application/json"
    assert store.content_types[manifest_artifact.object_uri] == "application/json"

    normalized_payload = json.loads(store.objects[normalized_artifact.object_uri])
    manifest_payload = json.loads(store.objects[manifest_artifact.object_uri])
    assert normalized_payload["schema_version"] == "1"
    assert manifest_payload["schema_version"] == "1"
    assert manifest_payload["chunks"][0]["chunk_id"] == chunks[0].chunk_id
