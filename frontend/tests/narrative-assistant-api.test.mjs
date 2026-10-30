import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
const { api, setAccessTokenProvider } = await import(`data:text/javascript;base64,${Buffer.from(outputText + "\n//# sourceURL=assistant-api-test.js").toString("base64")}`);

test("assistant calls are project scoped, authenticated, abortable and uncached when polled", async () => {
  const original = globalThis.fetch, calls = [];
  setAccessTokenProvider(async () => "fixture-access-token");
  globalThis.fetch = async (path, init) => {
    calls.push({ path, init });
    return new Response("{}", { status: 200 });
  };
  try {
    const { signal } = new AbortController();
    const base = "/v1/narrative/projects/project/assistant";
    await api.listAssistantThreads("workspace", "project", { signal });
    await api.createAssistantThread("workspace", "project", "Story chat", "thread-key", signal);
    await api.listAssistantTurns("workspace", "project", "thread", { signal });
    await api.postAssistantTurn("workspace", "project", "thread",
      { request: "Add a storm.", base_revision_id: "rev", focus_node: "opening", idempotency_key: "turn-key" }, signal);
    await api.cancelAssistantTurn("workspace", "project", "thread", "turn", signal);
    await api.getAssistantProposal("workspace", "project", "proposal", signal);
    await api.acceptAssistantProposal("workspace", "project", "proposal", "decision-key", signal);
    await api.rejectAssistantProposal("workspace", "project", "proposal", signal);
    assert.deepEqual(calls.map(({ path, init }) => [init.method ?? "GET", path]), [
      ["GET", `${base}/threads?limit=25`],
      ["POST", `${base}/threads`],
      ["GET", `${base}/threads/thread/turns?limit=100`],
      ["POST", `${base}/threads/thread/turns`],
      ["POST", `${base}/threads/thread/turns/turn/cancel`],
      ["GET", `${base}/proposals/proposal`],
      ["POST", `${base}/proposals/proposal/accept`],
      ["POST", `${base}/proposals/proposal/reject`],
    ]);
    assert.deepEqual(JSON.parse(calls[1].init.body), { title: "Story chat", idempotency_key: "thread-key" });
    assert.deepEqual(JSON.parse(calls[3].init.body), {
      request: "Add a storm.", base_revision_id: "rev", focus_node: "opening", idempotency_key: "turn-key",
    });
    assert.deepEqual(JSON.parse(calls[6].init.body), { idempotency_key: "decision-key" });
    assert.ok(calls.every(({ init }) => init.signal === signal && init.headers["X-Tenant-ID"] === "workspace"
      && init.headers.Authorization === "Bearer fixture-access-token"));
    assert.deepEqual(calls.filter(({ init }) => !init.method).map(({ init }) => init.cache), ["no-store", "no-store", "no-store"]);
  } finally { globalThis.fetch = original; setAccessTokenProvider(null); }
});
