"""Private create-only release objects, separate from mutable ingestion storage.

Database metadata is authoritative. Never trust object metadata/ETags as content
verification, and never return a public/presigned URL from this adapter.
"""

import asyncio
import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from flint_graph.infrastructure.object_store import object_uri

MAX_BYTES = 64 * 1024 * 1024


class ArtifactStoreError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ObjectReceipt:
    key: str
    sha256: str
    size_bytes: int


def release_artifact_key(
    *,
    tenant_id: UUID,
    release_id: UUID,
    job_id: UUID,
    execution_token: UUID,
    kind: Literal["source", "web", "manifest"],
) -> str:
    names = {"source": "source.zip", "web": "web.zip", "manifest": "manifest.json"}
    if kind not in names:
        raise ValueError("Invalid release artifact kind")
    return (
        f"tenants/{tenant_id}/narrative/releases/{release_id}/jobs/{job_id}/"
        f"executions/{execution_token}/{names[kind]}"
    )


def asset_object_key(
    *,
    tenant_id: UUID,
    project_id: UUID,
    asset_id: UUID,
    variant: Literal["image", "thumbnail", "font", "audio", "music"],
) -> str:
    if variant not in ("image", "thumbnail", "font", "audio", "music"):
        raise ValueError("Invalid asset variant")
    name = {"font": "font.bin", "audio": "voice.wav", "music": "music.ogg"}.get(
        variant, f"{variant}.png"
    )
    return f"tenants/{tenant_id}/narrative/projects/{project_id}/assets/{asset_id}/{name}"


def voice_reference_object_key(
    *, tenant_id: UUID | str, project_id: UUID | str, reference_id: UUID | str
) -> str:
    """Private reference audio (#175): outside ``assets/``, so nothing can bind or ship it."""
    tenant, project, reference = (
        UUID(str(value)) for value in (tenant_id, project_id, reference_id)
    )
    return (
        f"tenants/{tenant}/narrative/projects/{project}/voice-references/{reference}/reference.wav"
    )


def assistant_image_object_key(*, tenant_id: UUID, project_id: UUID, image_id: UUID) -> str:
    """A picture attached to a message (ADR 0076): under the project, so it goes with it."""
    return (
        f"tenants/{tenant_id}/narrative/projects/{project_id}/assistant-images/{image_id}/image.png"
    )


_REFERENCE_KEY = re.compile(
    r"tenants/[0-9a-f-]{36}/narrative/projects/[0-9a-f-]{36}/voice-references/[0-9a-f-]{36}/reference\.wav"
)


class S3NarrativeArtifactStore:
    def __init__(self, client: Any, *, bucket: str) -> None:
        object_uri(bucket, "validate")
        self.client, self.bucket = client, bucket

    async def put_private_adapter(
        self, key: str, data: bytes, *, expected_sha256: str
    ) -> ObjectReceipt:
        from flint_graph.narrative.style_weights import MAX_ADAPTER_BYTES

        if not re.fullmatch(
            r"tenants/[0-9a-f-]{36}/narrative/projects/[0-9a-f-]{36}/style-adapters/"
            r"[0-9a-f-]{36}/executions/[0-9a-f-]{36}/adapter\.safetensors",
            key,
        ):
            raise ValueError("Invalid private adapter key")
        self._expect(key, len(data), expected_sha256, MAX_ADAPTER_BYTES)
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise ArtifactStoreError("artifact_integrity")
        return await asyncio.to_thread(
            self._put, key, data, expected_sha256, "application/octet-stream"
        )

    def _expect(self, key: str, size: int, sha256: str, cap: int) -> None:
        if (
            type(cap) is not int
            or not 1 <= cap <= MAX_BYTES
            or type(size) is not int
            or not 1 <= size <= cap
            or not isinstance(sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", sha256)
        ):
            raise ValueError("Invalid artifact expectation")
        object_uri(self.bucket, key)

    def _read(self, key: str, size: int, sha256: str) -> bytes:
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=key)
            if type(head["ContentLength"]) is not int or head["ContentLength"] != size:
                raise ArtifactStoreError("artifact_integrity")
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            body = response["Body"]
            try:
                result = bytearray()
                while True:
                    requested = min(65536, size + 1 - len(result))
                    chunk = body.read(requested)
                    if not isinstance(chunk, bytes) or len(chunk) > requested:
                        raise ArtifactStoreError("artifact_integrity")
                    if not chunk:
                        break
                    result.extend(chunk)
                    if len(result) > size:
                        raise ArtifactStoreError("artifact_integrity")
                if len(result) != size or hashlib.sha256(result).hexdigest() != sha256:
                    raise ArtifactStoreError("artifact_integrity")
                return bytes(result)
            finally:
                body.close()
        except ArtifactStoreError:
            raise
        except Exception:
            # SDK errors may embed private keys/headers. Expose only a safe code.
            raise ArtifactStoreError("artifact_unavailable") from None

    async def get_verified(
        self,
        key: str,
        *,
        expected_size: int,
        expected_sha256: str,
        max_bytes: int = MAX_BYTES,
    ) -> bytes:
        self._expect(key, expected_size, expected_sha256, max_bytes)
        return await asyncio.to_thread(self._read, key, expected_size, expected_sha256)

    def _put(self, key: str, data: bytes, sha256: str, content_type: str) -> ObjectReceipt:
        conflict = False
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                Metadata={"sha256": sha256},
                IfNoneMatch="*",
            )
        except Exception as error:
            response = getattr(error, "response", {})
            metadata = response.get("ResponseMetadata") if isinstance(response, dict) else None
            status = metadata.get("HTTPStatusCode") if isinstance(metadata, dict) else None
            if status not in (409, 412):
                raise ArtifactStoreError("artifact_unavailable") from None
            conflict = status == 412
        try:
            self._read(key, len(data), sha256)
        except ArtifactStoreError as error:
            if conflict and error.code == "artifact_integrity":
                raise ArtifactStoreError("artifact_conflict") from None
            raise
        return ObjectReceipt(key, sha256, len(data))

    def _delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception:
            raise ArtifactStoreError("artifact_unavailable") from None

    async def delete_reference(self, key: str) -> None:
        """Remove deleted reference audio; every other artifact stays create-only."""
        if not _REFERENCE_KEY.fullmatch(key):
            raise ValueError("Only voice reference audio can be deleted")
        await asyncio.to_thread(self._delete, key)

    def _delete_prefix(self, prefix: str) -> None:
        """List and delete until nothing is left, so a retry simply carries on."""
        try:
            while True:
                found = self.client.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
                keys = [{"Key": item["Key"]} for item in found.get("Contents", [])]
                if not keys:
                    return
                result = self.client.delete_objects(
                    Bucket=self.bucket, Delete={"Objects": keys, "Quiet": True}
                )
                if result.get("Errors"):
                    raise ArtifactStoreError("artifact_unavailable")
        except ArtifactStoreError:
            raise
        except Exception:
            # SDK errors may embed private keys/headers. Expose only a safe code.
            raise ArtifactStoreError("artifact_unavailable") from None

    async def delete_project_files(
        self, *, tenant_id: UUID, project_id: UUID, release_ids: Sequence[UUID]
    ) -> None:
        """Remove all of a project's files and its releases' (ADR 0073). Everything else in this
        store stays create-only. IDs are parsed first, so no other prefix can be named."""
        tenant, project = (UUID(str(value)) for value in (tenant_id, project_id))
        prefixes = [
            f"tenants/{tenant}/narrative/projects/{project}/",
            *(f"tenants/{tenant}/narrative/releases/{UUID(str(item))}/" for item in release_ids),
        ]
        for prefix in prefixes:
            await asyncio.to_thread(self._delete_prefix, prefix)

    async def put_once(
        self,
        key: str,
        data: bytes,
        *,
        expected_sha256: str,
        content_type: str,
        max_bytes: int = MAX_BYTES,
    ) -> ObjectReceipt:
        self._expect(key, len(data), expected_sha256, max_bytes)
        if not isinstance(data, bytes) or hashlib.sha256(data).hexdigest() != expected_sha256:
            raise ArtifactStoreError("artifact_integrity")
        if content_type not in (
            "application/zip",
            "application/json",
            "image/png",
            "font/ttf",
            "font/otf",
            "audio/wav",
            "audio/ogg",
        ):
            raise ValueError("Invalid narrative artifact content type")
        return await asyncio.to_thread(self._put, key, data, expected_sha256, content_type)
