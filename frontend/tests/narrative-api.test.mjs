import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } });
const { api, setAccessTokenProvider } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
);

test("studio discovery is scoped, abortable and independent of search readiness", async () => {
  const original = globalThis.fetch, calls = [];
  globalThis.fetch = async (path, init) => {
    calls.push({ path, init });
    return new Response("[]", { status: 200 });
  };
  try {
    const { signal } = new AbortController();
    await api.listNarrativeProjects("workspace", { beforeId: "cursor", limit: 25, signal });
    await api.getNarrativeProject("workspace", "project", signal);
    await api.listNarrativeRevisions("workspace", "project", { beforeId: "revision", signal });
    await api.getNarrativeRevision("workspace", "project", "revision", signal);
    assert.equal(calls.length, 4);
    const list = new URL(calls[0].path, "http://test");
    assert.equal(list.pathname, "/v1/narrative/projects");
    assert.equal(list.searchParams.get("before_id"), "cursor");
    assert.equal(list.searchParams.get("limit"), "25");
    assert.equal(calls[1].path, "/v1/narrative/projects/project");
    assert.equal(calls[3].path, "/v1/narrative/projects/project/revisions/revision");
    assert.ok(calls.every(({ init }) => !init.method && init.signal === signal
      && init.headers["X-Tenant-ID"] === "workspace"));
  } finally { globalThis.fetch = original; }
});

test("author saves retain their explicit base and retry key and surface saved conflicts", async () => {
  const original = globalThis.fetch, calls = [];
  setAccessTokenProvider(async () => "fixture-access-token");
  globalThis.fetch = async (path, init) => {
    calls.push({ path, init });
    return new Response(JSON.stringify({ type: "urn:flint-graph:error:stale-revision", status: 409,
      detail: "Your draft was retained.", errors: [{ code: "stale_revision",
        conflict_revision_id: "conflict", observed_head_revision_id: "current" }] }),
    { status: 409, headers: { "Content-Type": "application/problem+json" } });
  };
  try {
    const payload = { base_revision_id: "base", idempotency_key: "stable-key",
      story_json: '{"original":"draft"}', notices: "Original notices" };
    const { signal } = new AbortController();
    for (let attempt = 0; attempt < 2; attempt += 1) {
      await assert.rejects(api.saveNarrativeRevision("workspace", "project", payload, signal),
        error => error.status === 409 && error.problem.errors[0].conflict_revision_id === "conflict");
    }
    assert.equal(calls[0].init.body, calls[1].init.body);
    assert.deepEqual(JSON.parse(calls[0].init.body), payload);
    assert.equal(calls[0].init.headers.Authorization, "Bearer fixture-access-token");
    assert.ok(!calls[0].init.body.includes("fixture-access-token"));
  } finally { globalThis.fetch = original; setAccessTokenProvider(null); }
});

test("project creation reuses the author's request identity without model or readiness setup", async () => {
  const original = globalThis.fetch, calls = [];
  globalThis.fetch = async (path, init) => {
    calls.push({ path, init });
    return new Response("{}", { status: 201 });
  };
  try {
    const { signal } = new AbortController();
    await api.createNarrativeProject("workspace", "Original mystery", "stable-create", signal);
    await api.createNarrativeProject("workspace", "Original mystery", "stable-create", signal);
    assert.equal(calls[0].path, "/v1/narrative/projects");
    assert.equal(calls[0].init.body, calls[1].init.body);
    assert.deepEqual(JSON.parse(calls[0].init.body), {
      name: "Original mystery", idempotency_key: "stable-create",
    });
    assert.ok(calls.every(({ init }) => init.method === "POST" && init.signal === signal));
  } finally { globalThis.fetch = original; }
});
