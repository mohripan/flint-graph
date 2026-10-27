"""Explicit real-HTTP proof against an owned local dev-auth narrative API.

Creates a new synthetic workspace/project; never reads existing documents or
changes existing workspaces. Use only an isolated development database/server.
"""

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    endpoint = urlparse(args.url)
    if (
        endpoint.scheme != "http"
        or endpoint.hostname not in {"127.0.0.1", "localhost"}
        or endpoint.username
        or endpoint.password
        or endpoint.path not in {"", "/"}
        or endpoint.query
        or endpoint.fragment
    ):
        parser.error("Select an owned loopback dev-auth API origin")
    if args.output.exists() or args.output.is_symlink():
        parser.error("Evidence output must be new")
    if not args.output.parent.is_dir():
        parser.error("Evidence output parent must already exist")
    events = []
    run_id = uuid4().hex
    with httpx.Client(
        base_url=args.url, timeout=15, headers={"X-Dev-User": "narrative-http-qualification"}
    ) as client:

        def request(method, path, expected, **kwargs):
            response = client.request(method, path, **kwargs)
            events.append({"method": method, "path": path, "status": response.status_code})
            if response.status_code != expected:
                raise RuntimeError(f"Unexpected status for {method} {path}: {response.status_code}")
            return response.json()

        workspace = request(
            "POST", "/v1/workspaces", 201, json={"name": "Narrative HTTP proof " + run_id}
        )
        client.headers["X-Tenant-ID"] = workspace["id"]
        spec = {"name": "An original local mystery", "idempotency_key": str(uuid4())}
        project = request("POST", "/v1/narrative/projects", 201, json=spec)
        assert request("POST", "/v1/narrative/projects", 201, json=spec)["id"] == project["id"]
        path = "/v1/narrative/projects/" + project["id"]
        base = request("GET", path + "/revisions/" + project["head_revision_id"], 200)
        story = json.loads(base["story_json"])
        story["nodes"]["opening"]["text"] = "We follow the lantern along the river."
        edit = {
            "base_revision_id": base["id"],
            "idempotency_key": str(uuid4()),
            "story_json": json.dumps(story),
            "notices": "Original HTTP qualification prose.\n",
        }
        accepted = request("POST", path + "/revisions", 201, json=edit)
        assert request("POST", path + "/revisions", 201, json=edit)["id"] == accepted["id"]
        story["nodes"]["opening"]["text"] = "We search the archive before following the river."
        stale = {**edit, "idempotency_key": str(uuid4()), "story_json": json.dumps(story)}
        conflict = request("POST", path + "/revisions", 409, json=stale)
        conflict_id = conflict["errors"][0]["conflict_revision_id"]
        recovered = request("GET", path + "/revisions/" + conflict_id, 200)
        assert json.loads(recovered["story_json"]) == story and recovered["conflicted"] is True
        assert request("POST", path + "/revisions", 409, json=stale) == conflict
        assert request("GET", path, 200)["head_revision_id"] == accepted["id"]
        assert len(request("GET", path + "/revisions", 200)) == 3
        archive = {"base_revision_id": accepted["id"], "archived": True}
        assert request("POST", path + "/archive", 200, json=archive)["archived_at"]
        request("GET", path, 404)
        request("GET", path + "?include_archived=true", 200)
        assert (
            request("POST", path + "/archive", 200, json={**archive, "archived": False})[
                "archived_at"
            ]
            is None
        )
    report = {
        "passed": True,
        "api": args.url,
        "workspace_id": workspace["id"],
        "project_id": project["id"],
        "head_revision_id": accepted["id"],
        "conflict_revision_id": conflict_id,
        "content_hash": accepted["content_hash"],
        "events": events,
        "mode": "explicit owned local dev-auth proof",
    }
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": True, "requests": len(events), "evidence": str(args.output)}))


if __name__ == "__main__":
    main()
