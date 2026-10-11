import asyncio
import socket
from collections.abc import Mapping
from hashlib import sha256

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.api.dependencies import get_object_store, get_url_fetcher
from flint_graph.application.services.intake import create_upload_intake
from flint_graph.application.services.tenants import create_tenant
from flint_graph.domain.enums import DocumentVersionStatus, SourceType
from flint_graph.infrastructure.db.models import Document, DocumentVersion, IngestionJob
from flint_graph.infrastructure.object_store import ObjectInfo
from flint_graph.infrastructure.url_fetcher import FetchedURL, HTTPURLFetcher
from flint_graph.main import app


class FakeObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.metadata: dict[str, dict[str, str]] = {}
        self.content_types: dict[str, str] = {}
        self.put_count = 0

    async def put_bytes(
        self,
        uri: str,
        data: bytes,
        *,
        content_type: str,
        metadata: Mapping[str, str] | None = None,
    ) -> None:
        self.put_count += 1
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


class FakeURLFetcher:
    def __init__(self, responses: dict[str, tuple[bytes, str]]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    async def fetch(self, url: str) -> FetchedURL:
        self.calls.append(url)
        body, content_type = self.responses[url]
        return FetchedURL(body=body, content_type=content_type, final_url=url)


async def test_upload_intake_materializes_raw_source_and_queues_job(
    client: httpx.AsyncClient,
) -> None:
    store = FakeObjectStore()
    app.dependency_overrides[get_object_store] = lambda: store
    tenant_id = (await client.post("/v1/tenants", json={"name": "Upload Intake"})).json()["id"]
    body = b"# Upload\n\nFlintGraph intake."
    expected_hash = f"sha256:{sha256(body).hexdigest()}"

    response = await client.post(
        "/v1/documents/uploads",
        headers={"X-Tenant-ID": tenant_id, "Idempotency-Key": "upload-intake-001"},
        data={"title": "Uploaded Markdown", "external_id": "upload-001"},
        files={"file": ("note.md", body, "text/markdown")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["source_type"] == "upload"
    assert payload["source_uri"] is None
    assert payload["version_number"] == 1
    assert payload["job_status"] == "queued"
    assert payload["content_hash"] == expected_hash
    assert payload["object_uri"].startswith(
        f"s3://flint-graph/tenants/{tenant_id}/documents/{payload['document_id']}/"
        f"versions/{payload['document_version_id']}/raw/source"
    )
    assert store.objects[payload["object_uri"]] == body
    assert store.content_types[payload["object_uri"]] == "text/markdown"
    assert store.metadata[payload["object_uri"]] == {
        "content-hash": expected_hash,
        "content-type": "text/markdown",
        "original-filename": "note.md",
        "size-bytes": str(len(body)),
        "source-type": "upload",
    }

    events = await client.get(
        f"/v1/ingestion-jobs/{payload['ingestion_job_id']}/events",
        headers={"X-Tenant-ID": tenant_id},
    )
    assert events.status_code == 200
    assert [event["event_type"] for event in events.json()] == ["job.queued"]


async def test_upload_intake_idempotency_replay_returns_existing_job_without_rewriting_object(
    client: httpx.AsyncClient,
) -> None:
    store = FakeObjectStore()
    app.dependency_overrides[get_object_store] = lambda: store
    tenant_id = (await client.post("/v1/tenants", json={"name": "Upload Replay"})).json()["id"]

    first = await client.post(
        "/v1/documents/uploads",
        headers={"X-Tenant-ID": tenant_id, "Idempotency-Key": "upload-replay-001"},
        data={"title": "Replay Upload"},
        files={"file": ("note.txt", b"same content", "text/plain")},
    )
    second = await client.post(
        "/v1/documents/uploads",
        headers={"X-Tenant-ID": tenant_id, "Idempotency-Key": "upload-replay-001"},
        data={"title": "Replay Upload"},
        files={"file": ("note.txt", b"same content", "text/plain")},
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()
    assert store.put_count == 1


async def test_upload_intake_idempotency_reuse_with_different_bytes_returns_conflict(
    client: httpx.AsyncClient,
) -> None:
    store = FakeObjectStore()
    app.dependency_overrides[get_object_store] = lambda: store
    tenant_id = (await client.post("/v1/tenants", json={"name": "Upload Conflict"})).json()["id"]

    first = await client.post(
        "/v1/documents/uploads",
        headers={"X-Tenant-ID": tenant_id, "Idempotency-Key": "upload-conflict-001"},
        data={"title": "Conflict Upload"},
        files={"file": ("note.txt", b"first", "text/plain")},
    )
    second = await client.post(
        "/v1/documents/uploads",
        headers={"X-Tenant-ID": tenant_id, "Idempotency-Key": "upload-conflict-001"},
        data={"title": "Conflict Upload"},
        files={"file": ("note.txt", b"second", "text/plain")},
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["type"] == "urn:flint-graph:error:conflict"
    assert store.put_count == 1


async def test_url_intake_fetches_and_materializes_raw_source(
    client: httpx.AsyncClient,
) -> None:
    store = FakeObjectStore()
    fetcher = FakeURLFetcher(
        {"https://example.test/page": (b"<html><body>Acme</body></html>", "text/html")}
    )
    app.dependency_overrides[get_object_store] = lambda: store
    app.dependency_overrides[get_url_fetcher] = lambda: fetcher
    tenant_id = (await client.post("/v1/tenants", json={"name": "URL Intake"})).json()["id"]

    response = await client.post(
        "/v1/documents/from-url",
        headers={"X-Tenant-ID": tenant_id, "Idempotency-Key": "url-intake-001"},
        json={
            "title": "Fetched HTML",
            "source_url": "https://example.test/page",
            "external_id": "url-001",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert fetcher.calls == ["https://example.test/page"]
    assert payload["source_type"] == "url"
    assert payload["source_uri"] == "https://example.test/page"
    assert store.objects[payload["object_uri"]] == b"<html><body>Acme</body></html>"
    assert store.metadata[payload["object_uri"]]["source-url"] == "https://example.test/page"
    assert store.metadata[payload["object_uri"]]["source-type"] == "url"


@pytest.mark.parametrize("redirected", [False, True])
async def test_credential_bearing_url_intake_denies_before_document_job_or_object(
    client, redirected
):
    store = FakeObjectStore()
    requests = []

    def respond(request):
        requests.append(request.url.path)
        return httpx.Response(
            302, headers={"Location": "http://example-user:EXAMPLE_NOT_SECRET@127.0.0.1/report"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
        fetcher = HTTPURLFetcher(
            timeout_seconds=1, max_bytes=100, allow_private_addresses=True, http_client=http_client
        )
        app.dependency_overrides[get_object_store] = lambda: store
        app.dependency_overrides[get_url_fetcher] = lambda: fetcher
        tenant_id = (
            await client.post("/v1/tenants", json={"name": "Synthetic credential denial"})
        ).json()["id"]
        headers = {"X-Tenant-ID": tenant_id, "Idempotency-Key": "url-user-info-rejected"}
        response = await client.post(
            "/v1/documents/from-url",
            headers=headers,
            json={
                "title": "Synthetic credential denial",
                "source_url": "http://127.0.0.1/report"
                if redirected
                else "http://example-user:EXAMPLE_NOT_SECRET@127.0.0.1/report",
            },
        )
    assert response.status_code == 400
    assert "user information" in response.json()["detail"]
    assert "EXAMPLE_NOT_SECRET" not in response.text
    assert (await client.get("/v1/documents", headers=headers)).json() == []
    assert "ingestion_job_id" not in response.json()
    assert store.objects == {}
    assert requests == (["/report"] if redirected else [])


@pytest.mark.parametrize("dns_outcome", ["private", "failure", "slow"])
async def test_url_intake_dns_denial_precedes_persistence(client, monkeypatch, dns_outcome):
    store = FakeObjectStore()
    app.dependency_overrides[get_object_store] = lambda: store
    app.dependency_overrides[get_url_fetcher] = lambda: HTTPURLFetcher(
        timeout_seconds=0.02, max_bytes=100
    )
    tenant_id = (await client.post("/v1/tenants", json={"name": "Synthetic DNS denial"})).json()[
        "id"
    ]

    async def resolve(*args, **kwargs):
        if dns_outcome == "failure":
            raise socket.gaierror("SYNTHETIC_DNS_DIAGNOSTIC")
        if dns_outcome == "slow":
            await asyncio.sleep(0.1)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    response = await client.post(
        "/v1/documents/from-url",
        headers={"X-Tenant-ID": tenant_id, "Idempotency-Key": f"dns-denied-{dns_outcome}"},
        json={"title": "Synthetic DNS denial", "source_url": "http://denied.invalid/report"},
    )
    assert response.status_code == 400
    assert "SYNTHETIC_DNS_DIAGNOSTIC" not in response.text
    assert "ingestion_job_id" not in response.json()
    assert (await client.get("/v1/documents", headers={"X-Tenant-ID": tenant_id})).json() == []
    assert store.objects == {}


async def test_intake_requires_idempotency_key(client: httpx.AsyncClient) -> None:
    store = FakeObjectStore()
    app.dependency_overrides[get_object_store] = lambda: store
    tenant_id = (await client.post("/v1/tenants", json={"name": "Missing Idempotency"})).json()[
        "id"
    ]

    response = await client.post(
        "/v1/documents/uploads",
        headers={"X-Tenant-ID": tenant_id},
        data={"title": "Missing Idempotency"},
        files={"file": ("note.txt", b"content", "text/plain")},
    )

    assert response.status_code == 422
    assert store.objects == {}


async def test_upload_intake_persists_source_metadata_on_document_version(
    db_session: AsyncSession,
) -> None:
    store = FakeObjectStore()
    tenant = await create_tenant(db_session, name="Persisted Intake")

    record = await create_upload_intake(
        db_session,
        object_store=store,
        bucket="flint-graph",
        tenant_id=tenant.id,
        title="Persisted Upload",
        external_id="persisted-upload",
        idempotency_key="persisted-upload-001",
        data=b"persist me",
        content_type="text/plain",
        original_filename="persist.txt",
    )
    version = await db_session.get(DocumentVersion, record.job.document_version_id)
    document = await db_session.get(Document, record.job.document_id)
    jobs = list(await db_session.scalars(select(IngestionJob)))

    assert document is not None
    assert document.source_type == SourceType.UPLOAD
    assert document.source_uri is None
    assert version is not None
    assert version.status == DocumentVersionStatus.PENDING
    assert version.object_uri in store.objects
    assert version.content_hash == f"sha256:{sha256(b'persist me').hexdigest()}"
    assert version.metadata_ == {
        "intake": {
            "external_id": "persisted-upload",
            "title": "Persisted Upload",
        },
        "source": {
            "content_type": "text/plain",
            "original_filename": "persist.txt",
            "size_bytes": 10,
            "type": "upload",
        },
    }
    assert len(jobs) == 1
