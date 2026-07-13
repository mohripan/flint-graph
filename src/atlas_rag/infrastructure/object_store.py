from __future__ import annotations

from asyncio import to_thread
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Literal, Protocol
from urllib.parse import urlparse
from uuid import UUID

from atlas_rag.config import Settings


@dataclass(frozen=True)
class ObjectStoreURI:
    bucket: str
    key: str


@dataclass(frozen=True)
class ObjectInfo:
    size_bytes: int
    content_type: str | None
    metadata: dict[str, str]


class ObjectStore(Protocol):
    async def put_bytes(
        self,
        uri: str,
        data: bytes,
        *,
        content_type: str,
        metadata: Mapping[str, str] | None = None,
    ) -> None: ...

    async def get_bytes(self, uri: str) -> bytes: ...

    async def head_object(self, uri: str) -> ObjectInfo: ...


def parse_object_uri(uri: str) -> ObjectStoreURI:
    parsed = urlparse(uri)
    if parsed.scheme != "s3":
        raise ValueError(f"Unsupported object URI scheme: {parsed.scheme or '<missing>'}")
    if parsed.params or parsed.query or parsed.fragment:
        raise ValueError("Object URI must not include params, query, or fragment")
    if not parsed.netloc:
        raise ValueError("Object URI must include a bucket")
    if not parsed.path or parsed.path == "/":
        raise ValueError("Object URI must include an object key")
    if parsed.path.startswith("//"):
        raise ValueError("Object URI key must not start with a slash")

    key = parsed.path[1:]
    _validate_object_key(key)
    return ObjectStoreURI(bucket=parsed.netloc, key=key)


def object_uri(bucket: str, key: str) -> str:
    _validate_bucket(bucket)
    _validate_object_key(key)
    return f"s3://{bucket}/{key}"


def raw_source_object_key(*, tenant_id: UUID, document_id: UUID, version_id: UUID) -> str:
    return _version_prefix(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
    ) + "/raw/source"


def artifact_object_key(
    *,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
    artifact_name: str,
) -> str:
    _validate_artifact_name(artifact_name)
    return _version_prefix(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
    ) + f"/artifacts/{artifact_name}"


class S3ObjectStore:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def put_bytes(
        self,
        uri: str,
        data: bytes,
        *,
        content_type: str,
        metadata: Mapping[str, str] | None = None,
    ) -> None:
        parsed = parse_object_uri(uri)
        await to_thread(
            self._client.put_object,
            Bucket=parsed.bucket,
            Key=parsed.key,
            Body=data,
            ContentType=content_type,
            Metadata=_normalize_metadata(metadata or {}),
        )

    async def get_bytes(self, uri: str) -> bytes:
        parsed = parse_object_uri(uri)
        response = await to_thread(
            self._client.get_object,
            Bucket=parsed.bucket,
            Key=parsed.key,
        )
        body = response["Body"]
        data = await to_thread(body.read)
        if not isinstance(data, bytes):
            raise TypeError("S3 client returned non-byte object data")
        return data

    async def head_object(self, uri: str) -> ObjectInfo:
        parsed = parse_object_uri(uri)
        response = await to_thread(
            self._client.head_object,
            Bucket=parsed.bucket,
            Key=parsed.key,
        )
        content_length = response["ContentLength"]
        if not isinstance(content_length, int):
            raise TypeError("S3 client returned non-integer content length")

        content_type = response.get("ContentType")
        if content_type is not None and not isinstance(content_type, str):
            raise TypeError("S3 client returned non-string content type")

        metadata = response.get("Metadata", {})
        if not isinstance(metadata, Mapping):
            raise TypeError("S3 client returned non-mapping metadata")

        return ObjectInfo(
            size_bytes=content_length,
            content_type=content_type,
            metadata=_normalize_metadata(metadata),
        )


def create_object_store(settings: Settings) -> ObjectStore:
    if settings.object_store_provider == "s3":
        return create_s3_object_store(settings)
    _exhaustive_provider_check(settings.object_store_provider)


def create_s3_object_store(settings: Settings) -> S3ObjectStore:
    boto3: Any = import_module("boto3")
    botocore_config: Any = import_module("botocore.config")
    addressing_style = "path" if settings.object_store_force_path_style else "auto"
    config = botocore_config.Config(
        connect_timeout=settings.object_store_connect_timeout_seconds,
        read_timeout=settings.object_store_read_timeout_seconds,
        max_pool_connections=settings.object_store_max_pool_connections,
        s3={"addressing_style": addressing_style},
    )
    client = boto3.client(
        "s3",
        endpoint_url=settings.object_store_endpoint_url,
        aws_access_key_id=settings.object_store_access_key_id,
        aws_secret_access_key=settings.object_store_secret_access_key,
        region_name=settings.object_store_region,
        config=config,
    )
    return S3ObjectStore(client)


def _version_prefix(*, tenant_id: UUID, document_id: UUID, version_id: UUID) -> str:
    return f"tenants/{tenant_id}/documents/{document_id}/versions/{version_id}"


def _validate_bucket(bucket: str) -> None:
    if not bucket or "/" in bucket:
        raise ValueError("Object bucket must be non-empty and must not contain slashes")


def _validate_object_key(key: str) -> None:
    if not key:
        raise ValueError("Object key must be non-empty")
    if key.startswith("/") or key.endswith("/"):
        raise ValueError("Object key must not start or end with a slash")
    if "//" in key:
        raise ValueError("Object key must not contain empty path segments")


def _validate_artifact_name(artifact_name: str) -> None:
    if not artifact_name:
        raise ValueError("Artifact name must be non-empty")
    if artifact_name.startswith("/") or "\\" in artifact_name:
        raise ValueError("Artifact name must be relative")
    segments = artifact_name.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ValueError("Artifact name must not contain empty or relative path segments")


def _normalize_metadata(metadata: Mapping[str, object]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in metadata.items():
        if not isinstance(value, str):
            raise TypeError("Object metadata values must be strings")
        normalized_key = key.strip().lower().replace("_", "-")
        if not normalized_key:
            raise ValueError("Object metadata keys must be non-empty")
        normalized[normalized_key] = value
    return normalized


def _exhaustive_provider_check(provider: Literal["s3"]) -> None:
    raise ValueError(f"Unsupported object store provider: {provider}")
