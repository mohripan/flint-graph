import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
const { api, setAccessTokenProvider } = await import(`data:text/javascript;base64,${Buffer.from(outputText + "\n//# sourceURL=narrative-release-api-test.js").toString("base64")}`);
const releaseId = "11111111-1111-4111-8111-111111111111";
const artifact = { id: "artifact", kind: "source", size_bytes: 3, media_type: "application/zip",
  filename: "game-11111111111141118111111111111111-source.zip",
  sha256: "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad" };

test("release intents and inspection use scoped IDs, retained keys, abort signals and auth", async () => {
  const original = globalThis.fetch, calls = [];
  setAccessTokenProvider(async () => "fixture-access-token");
  globalThis.fetch = async (path, init) => {
    calls.push({ path, init });
    return new Response("{}", { status: 200 });
  };
  try {
    const { signal } = new AbortController();
    await api.listNarrativeReleases("workspace", "project", { beforeId: "cursor", signal });
    await api.createNarrativeRelease("workspace", "project", "revision", "same-key", signal);
    await api.createNarrativeRelease("workspace", "project", "revision", "same-key", signal);
    await api.getNarrativeRelease("workspace", "project", releaseId, signal);
    await api.retryNarrativeRelease("workspace", "project", releaseId, "retry-key", signal);
    await api.cancelNarrativeRelease("workspace", "project", releaseId, "job", signal);
    await api.listNarrativeReleaseJobs("workspace", "project", releaseId, { signal });
    await api.listNarrativeReleaseEvents("workspace", "project", releaseId, "job", { afterSequence: 3, signal });
    assert.equal(calls[0].path, "/v1/narrative/projects/project/releases?limit=25&before_id=cursor");
    assert.deepEqual(JSON.parse(calls[1].init.body), { revision_id: "revision", idempotency_key: "same-key" });
    assert.equal(calls[1].init.body, calls[2].init.body);
    assert.equal(calls[4].path, `/v1/narrative/projects/project/releases/${releaseId}/retry`);
    assert.equal(calls[5].path, `/v1/narrative/projects/project/releases/${releaseId}/jobs/job/cancel`);
    assert.ok(calls[7].path.endsWith("/jobs/job/events?limit=100&after_sequence=3"));
    assert.ok(calls.every(({ init }) => init.signal === signal && init.headers["X-Tenant-ID"] === "workspace"
      && init.headers.Authorization === "Bearer fixture-access-token"));
    assert.ok(calls.every(({ init }) => !init.body?.includes("story_json")));
    // Polled release state must come from the server, never an HTTP cache.
    assert.deepEqual(calls.map(({ init }) => init.cache ?? null),
      ["no-store", null, null, "no-store", null, null, "no-store", "no-store"]);
  } finally { globalThis.fetch = original; setAccessTokenProvider(null); }
});

test("attachment download is authenticated, private, bounded and verified before a Blob is returned", async () => {
  const original = globalThis.fetch;
  setAccessTokenProvider(async () => "fixture-access-token");
  globalThis.fetch = async (path, init) => {
    assert.equal(path, `/v1/narrative/projects/project/releases/${releaseId}/artifacts/source`);
    assert.equal(init.headers.Authorization, "Bearer fixture-access-token");
    assert.equal(init.headers["X-Tenant-ID"], "workspace");
    assert.equal(init.cache, "no-store");
    assert.equal(init.redirect, "error");
    return new Response("abc", { headers: { "Content-Type": "application/zip", "Content-Length": "3" } });
  };
  try {
    const blob = await api.downloadNarrativeArtifact("workspace", "project", releaseId, artifact);
    assert.equal(blob.size, 3);
    assert.equal(blob.type, "application/zip");
    assert.equal(await blob.text(), "abc");
  } finally { globalThis.fetch = original; setAccessTokenProvider(null); }
});

test("revoked access and corrupted/truncated/oversized attachments never become downloadable Blobs", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: "Access changed" }), { status: 403 });
    await assert.rejects(api.downloadNarrativeArtifact("workspace", "project", releaseId, artifact),
      error => error.status === 403 && error.message === "Access changed");
    for (const body of ["ab", "abd", "abcd"]) {
      globalThis.fetch = async () => new Response(body, { headers: { "Content-Type": "application/zip" } });
      await assert.rejects(api.downloadNarrativeArtifact("workspace", "project", releaseId, artifact),
        error => error.status === 502 && !error.message.includes(body));
    }
    let cancelled = false;
    globalThis.fetch = async () => new Response(new ReadableStream({
      start(controller) { controller.enqueue(new TextEncoder().encode("abcd")); },
      cancel() { cancelled = true; },
    }), { headers: { "Content-Type": "application/zip" } });
    await assert.rejects(api.downloadNarrativeArtifact("workspace", "project", releaseId, artifact));
    assert.equal(cancelled, true);
  } finally { globalThis.fetch = original; }
});

test("foreign metadata, unsafe names and an aborted scope never start a download", async () => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; throw new Error("must not fetch"); };
  try {
    for (const changed of [{ ...artifact, filename: "../../creator-project.zip" },
      { ...artifact, size_bytes: 67108865 }]) {
      await assert.rejects(api.downloadNarrativeArtifact("workspace", "project", releaseId, changed),
        error => error.status === 502);
    }
    let finishAuth;
    setAccessTokenProvider(() => new Promise(resolve => { finishAuth = resolve; }));
    const controller = new AbortController();
    const download = api.downloadNarrativeArtifact("workspace", "project", releaseId, artifact, controller.signal);
    controller.abort(); finishAuth("fixture-access-token");
    await assert.rejects(download, error => error.name === "AbortError");
    assert.equal(calls, 0);
  } finally { globalThis.fetch = original; setAccessTokenProvider(null); }
});
