from io import BytesIO
from uuid import UUID

import pytest

from atlas_rag.infrastructure.object_store import (
    S3ObjectStore,
    artifact_object_key,
    object_uri,
    parse_object_uri,
    raw_source_object_key,
)


def test_parse_object_uri_accepts_internal_s3_references() -> None:
    parsed = parse_object_uri(
        "s3://atlas-rag/tenants/tenant-id/documents/document-id/versions/version-id/raw/source"
    )

    assert parsed.bucket == "atlas-rag"
    assert parsed.key == "tenants/tenant-id/documents/document-id/versions/version-id/raw/source"


@pytest.mark.parametrize(
    "uri",
    [
        "https://atlas-rag/tenants/tenant-id/raw/source",
        "s3://",
        "s3://atlas-rag",
        "s3:///tenants/tenant-id/raw/source",
        "s3://atlas-rag//tenants/tenant-id/raw/source",
    ],
)
def test_parse_object_uri_rejects_unsupported_or_malformed_references(uri: str) -> None:
    with pytest.raises(ValueError):
        parse_object_uri(uri)


def test_object_key_generation_is_deterministic_and_version_scoped() -> None:
    tenant_id = UUID("11111111-1111-4111-8111-111111111111")
    document_id = UUID("22222222-2222-4222-8222-222222222222")
    version_id = UUID("33333333-3333-4333-8333-333333333333")

    assert raw_source_object_key(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
    ) == (
        "tenants/11111111-1111-4111-8111-111111111111/"
        "documents/22222222-2222-4222-8222-222222222222/"
        "versions/33333333-3333-4333-8333-333333333333/raw/source"
    )
    assert artifact_object_key(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        artifact_name="normalized.json",
    ) == (
        "tenants/11111111-1111-4111-8111-111111111111/"
        "documents/22222222-2222-4222-8222-222222222222/"
        "versions/33333333-3333-4333-8333-333333333333/artifacts/normalized.json"
    )
    assert object_uri("atlas-rag", raw_source_object_key(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
    )) == (
        "s3://atlas-rag/tenants/11111111-1111-4111-8111-111111111111/"
        "documents/22222222-2222-4222-8222-222222222222/"
        "versions/33333333-3333-4333-8333-333333333333/raw/source"
    )


@pytest.mark.parametrize("artifact_name", ["/normalized.json", "../normalized.json", ""])
def test_artifact_key_rejects_unsafe_artifact_names(artifact_name: str) -> None:
    with pytest.raises(ValueError):
        artifact_object_key(
            tenant_id=UUID("11111111-1111-4111-8111-111111111111"),
            document_id=UUID("22222222-2222-4222-8222-222222222222"),
            version_id=UUID("33333333-3333-4333-8333-333333333333"),
            artifact_name=artifact_name,
        )


class FakeS3Client:
    def __init__(self) -> None:
        self.put_calls: list[dict[str, object]] = []
        self.objects: dict[tuple[str, str], bytes] = {}
        self.metadata: dict[tuple[str, str], dict[str, str]] = {}

    def put_object(self, **kwargs: object) -> None:
        bucket = str(kwargs["Bucket"])
        key = str(kwargs["Key"])
        body = kwargs["Body"]
        assert isinstance(body, bytes)
        self.put_calls.append(kwargs)
        self.objects[(bucket, key)] = body
        self.metadata[(bucket, key)] = dict(kwargs["Metadata"])  # type: ignore[arg-type]

    def get_object(self, **kwargs: object) -> dict[str, object]:
        bucket = str(kwargs["Bucket"])
        key = str(kwargs["Key"])
        return {"Body": BytesIO(self.objects[(bucket, key)])}

    def head_object(self, **kwargs: object) -> dict[str, object]:
        bucket = str(kwargs["Bucket"])
        key = str(kwargs["Key"])
        data = self.objects[(bucket, key)]
        return {
            "ContentLength": len(data),
            "ContentType": "text/plain",
            "Metadata": self.metadata[(bucket, key)],
        }


async def test_s3_object_store_writes_reads_and_normalizes_metadata() -> None:
    client = FakeS3Client()
    store = S3ObjectStore(client)
    uri = "s3://atlas-rag/tenants/t/documents/d/versions/v/raw/source"

    await store.put_bytes(
        uri,
        b"hello",
        content_type="text/plain",
        metadata={
            "Content_Hash": "sha256:abc123",
            "Original-Filename": "Note.md",
        },
    )
    body = await store.get_bytes(uri)
    info = await store.head_object(uri)

    assert client.put_calls == [
        {
            "Bucket": "atlas-rag",
            "Key": "tenants/t/documents/d/versions/v/raw/source",
            "Body": b"hello",
            "ContentType": "text/plain",
            "Metadata": {
                "content-hash": "sha256:abc123",
                "original-filename": "Note.md",
            },
        }
    ]
    assert body == b"hello"
    assert info.size_bytes == 5
    assert info.content_type == "text/plain"
    assert info.metadata == {
        "content-hash": "sha256:abc123",
        "original-filename": "Note.md",
    }
