from uuid import UUID

import httpx


async def test_register_document_and_create_idempotent_ingestion_job(
    client: httpx.AsyncClient,
) -> None:
    tenant_response = await client.post("/v1/tenants", json={"name": "Acme Research"})
    assert tenant_response.status_code == 201
    tenant_id = tenant_response.json()["id"]
    UUID(tenant_id)

    headers = {"X-Tenant-ID": tenant_id}
    document_response = await client.post(
        "/v1/documents",
        headers=headers,
        json={
            "title": "Graph Retrieval Architecture",
            "source_type": "url",
            "source_uri": "https://example.test/graph-retrieval",
            "external_id": "architecture-001",
        },
    )
    assert document_response.status_code == 201
    document_id = document_response.json()["id"]

    job_headers = {**headers, "Idempotency-Key": "ingest-architecture-001-v1"}
    first_job_response = await client.post(
        f"/v1/documents/{document_id}/ingestion-jobs",
        headers=job_headers,
    )
    assert first_job_response.status_code == 201
    first_job = first_job_response.json()
    assert first_job["status"] == "queued"
    assert first_job["version_number"] == 1

    repeated_job_response = await client.post(
        f"/v1/documents/{document_id}/ingestion-jobs",
        headers=job_headers,
    )
    assert repeated_job_response.status_code == 200
    assert repeated_job_response.json()["id"] == first_job["id"]

    second_job_response = await client.post(
        f"/v1/documents/{document_id}/ingestion-jobs",
        headers={**headers, "Idempotency-Key": "ingest-architecture-001-v2"},
    )
    assert second_job_response.status_code == 201
    assert second_job_response.json()["version_number"] == 2

    event_response = await client.get(
        f"/v1/ingestion-jobs/{first_job['id']}/events",
        headers=headers,
    )
    assert event_response.status_code == 200
    events = event_response.json()
    assert len(events) == 1
    assert events[0]["event_type"] == "job.queued"
    assert events[0]["details"] == {"document_version": 1}


async def test_tenant_boundary_returns_not_found(client: httpx.AsyncClient) -> None:
    tenant_a = (await client.post("/v1/tenants", json={"name": "Tenant A"})).json()["id"]
    tenant_b = (await client.post("/v1/tenants", json={"name": "Tenant B"})).json()["id"]

    document = (
        await client.post(
            "/v1/documents",
            headers={"X-Tenant-ID": tenant_a},
            json={"title": "Private", "source_type": "upload"},
        )
    ).json()

    response = await client.post(
        f"/v1/documents/{document['id']}/ingestion-jobs",
        headers={
            "X-Tenant-ID": tenant_b,
            "Idempotency-Key": "cross-tenant-attempt",
        },
    )
    assert response.status_code == 404


async def test_validation_errors_use_problem_details(client: httpx.AsyncClient) -> None:
    tenant_id = (await client.post("/v1/tenants", json={"name": "Validation Tenant"})).json()["id"]
    request_id = "request-validation-001"

    response = await client.post(
        "/v1/documents",
        headers={"X-Tenant-ID": tenant_id, "X-Request-ID": request_id},
        json={"title": "Missing URL", "source_type": "url"},
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["x-request-id"] == request_id
    problem = response.json()
    assert problem["request_id"] == request_id
    assert problem["type"] == "urn:flint-graph:error:validation"


async def test_duplicate_document_external_id_returns_conflict(client: httpx.AsyncClient) -> None:
    tenant_id = (await client.post("/v1/tenants", json={"name": "Conflict Tenant"})).json()["id"]
    headers = {"X-Tenant-ID": tenant_id}
    payload = {
        "title": "Architecture",
        "source_type": "url",
        "source_uri": "https://example.test/architecture",
        "external_id": "architecture-duplicate",
    }

    first = await client.post("/v1/documents", headers=headers, json=payload)
    second = await client.post("/v1/documents", headers=headers, json=payload)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["type"] == "urn:flint-graph:error:conflict"


async def test_health_endpoints(client: httpx.AsyncClient) -> None:
    live = await client.get("/health/live")
    ready = await client.get("/health/ready")

    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}
