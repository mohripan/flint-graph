import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } });
const { api } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

test("conversation discovery and reopening remain read-only, scoped and abortable", async () => {
  const calls = [], original = globalThis.fetch;
  globalThis.fetch = async (path, init) => {
    calls.push({ path, init });
    return new Response("{}", { status: 200 });
  };
  try {
    const { signal } = new AbortController();
    await api.listConversations("workspace-a", { query: " revenue %_ ", limit: 25, beforeId: "cursor", signal });
    await api.getConversation("workspace-a", "conversation-id", signal);
    await api.listConversationTurns("workspace-a", "conversation-id", { afterId: "turn-id", limit: 50, signal });
    const url = new URL(calls[0].path, "http://test");
    assert.equal(url.pathname, "/v1/conversations");
    assert.equal(url.searchParams.get("q"), "revenue %_");
    assert.equal(url.searchParams.get("before_id"), "cursor");
    assert.equal(url.searchParams.get("limit"), "25");
    assert.equal(calls[1].path, "/v1/conversations/conversation-id");
    const turns = new URL(calls[2].path, "http://test");
    assert.equal(turns.searchParams.get("after_id"), "turn-id");
    assert.equal(turns.searchParams.get("limit"), "50");
    assert.ok(calls.every(({ init }) => !init.method && init.signal === signal && init.headers["X-Tenant-ID"] === "workspace-a"));
  } finally { globalThis.fetch = original; }
});

test("conversation sends preserve the caller's retry key and never send a client transcript", async () => {
  const calls = [], original = globalThis.fetch;
  globalThis.fetch = async (path, init) => {
    calls.push({ path, init });
    return new Response("{}", { status: 200 });
  };
  try {
    const { signal } = new AbortController();
    await api.createConversation("workspace-a", "Research", signal);
    await api.createConversationTurn("workspace-a", "conversation-id", "What about the prior year?", "same-key", signal);
    await api.createConversationTurn("workspace-a", "conversation-id", "What about the prior year?", "same-key", signal);
    assert.equal(calls[0].path, "/v1/conversations");
    assert.deepEqual(JSON.parse(calls[0].init.body), { title: "Research" });
    assert.equal(calls[1].path, "/v1/conversations/conversation-id/turns");
    assert.deepEqual(JSON.parse(calls[1].init.body), { query: "What about the prior year?", idempotency_key: "same-key", stream: true });
    assert.equal(calls[1].init.body, calls[2].init.body);
    assert.ok(calls.every(({ init }) => init.method === "POST" && init.signal === signal));
    await api.renameConversation("workspace-a", "conversation-id", "Renamed", signal);
    assert.equal(calls[3].init.method, "PATCH");
    assert.deepEqual(JSON.parse(calls[3].init.body), { title: "Renamed" });
    await api.cancelQueuedConversationTurn("workspace-a", "conversation-id", "turn-id", signal);
    assert.equal(calls[4].path, "/v1/conversations/conversation-id/turns/turn-id/cancel");
    assert.equal(calls[4].init.method, "POST");
  } finally { globalThis.fetch = original; }
});
