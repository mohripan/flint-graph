import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const options = { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } };
const moduleUrl = (code, name) => `data:text/javascript;base64,${Buffer.from(`${code}\n//# sourceURL=${name}`).toString("base64")}`;
const apiCode = ts.transpileModule(await readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"), options).outputText;
const apiUrl = moduleUrl(apiCode, "stream-api.js");
const streamCode = ts.transpileModule(await readFile(new URL("../src/narrative/assistantStream.ts", import.meta.url), "utf8"), options)
  .outputText.replace(/from "\.\.\/lib\/api"/g, `from "${apiUrl}"`);
const stream = await import(moduleUrl(streamCode, "assistant-stream.js"));
const { ApiError, setAccessTokenProvider } = await import(apiUrl);

const frame = (sequence, kind, payload) =>
  `id: ${sequence}\nevent: ${kind}\ndata: ${JSON.stringify({ turn_id: "turn", sequence, attempt: 1, kind, payload, created_at: "2026-10-31T10:00:00Z" })}\n\n`;

test("frames are parsed across arbitrary chunk boundaries, CRLF and comments", () => {
  const text = `retry: 1000\n\n: keep-alive\n\n${frame(1, "text", { call: 1, text: "Hi" })}${frame(2, "status", { status: "completed" })}`.replace(/\n/g, "\r\n");
  for (const size of [1, 3, 7, text.length]) {
    const parser = new stream.SseFrames(), seen = [];
    for (let start = 0; start < text.length; start += size) seen.push(...parser.push(text.slice(start, start + size)));
    assert.deepEqual(seen.map(event => [event.sequence, event.kind]), [[1, "text"], [2, "status"]]);
  }
  assert.deepEqual(new stream.SseFrames().push("data: {not json}\n\nevent: x\n\n"), []);
});

function body(chunks) {
  return new ReadableStream({ start(controller) {
    for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk));
    controller.close();
  } });
}

test("the stream request is tenant scoped, authenticated, uncached and resumes from a sequence", async () => {
  const original = globalThis.fetch, calls = [];
  setAccessTokenProvider(async () => "fixture-access-token");
  globalThis.fetch = async (path, init) => {
    calls.push({ path, init });
    return path.includes("/stream") ? new Response(body([frame(4, "text", { call: 1, text: "a" }).slice(0, 20),
      frame(4, "text", { call: 1, text: "a" }).slice(20), frame(5, "status", { status: "failed" })]), { status: 200 })
      : new Response("[]", { status: 200 });
  };
  try {
    const received = [], { signal } = new AbortController();
    await stream.streamTurnEvents("workspace", "project", "thread", "turn", 3, { signal, onEvents: events => received.push(...events) });
    await stream.listTurnEvents("workspace", "project", "thread", "turn", 0, signal);
    const base = "/v1/narrative/projects/project/assistant/threads/thread/turns/turn/events";
    assert.deepEqual(calls.map(call => call.path), [`${base}/stream?after_sequence=3`, `${base}?after_sequence=0&limit=500`]);
    assert.ok(calls.every(({ init }) => init.signal === signal && init.cache === "no-store"
      && init.headers["X-Tenant-ID"] === "workspace" && init.headers.Authorization === "Bearer fixture-access-token"));
    assert.equal(calls[0].init.headers.Accept, "text/event-stream");
    assert.deepEqual(received.map(event => event.sequence), [4, 5]);
  } finally { globalThis.fetch = original; setAccessTokenProvider(null); }
});

test("errors keep the problem detail and status for access handling", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: "Assistant message was not found." }), { status: 404 });
  try {
    await assert.rejects(stream.streamTurnEvents("w", "p", "t", "x", 0, { onEvents: () => {} }),
      error => error instanceof ApiError && error.status === 404 && error.message === "Assistant message was not found.");
  } finally { globalThis.fetch = original; }
});

test("following reconnects from the last applied sequence until the turn ends", async () => {
  let cursor = 0, finished = false;
  const opened = [], waits = [];
  const outcomes = [
    async () => { cursor = 3; throw new TypeError("network lost"); },
    async () => { cursor = 7; },
    async () => { cursor = 9; finished = true; },
  ];
  await stream.followTurnEvents(async after => { opened.push(after); await outcomes[opened.length - 1](); },
    { cursor: () => cursor, finished: () => finished }, new AbortController().signal, async delay => { waits.push(delay); });
  assert.deepEqual(opened, [0, 3, 7]);
  assert.deepEqual(waits, [1000, 500]);

  const gone = new ApiError("Not found", 404);
  await assert.rejects(stream.followTurnEvents(async () => { throw gone; }, { cursor: () => 0, finished: () => false },
    new AbortController().signal, async () => {}), error => error === gone);
  const controller = new AbortController();
  let attempts = 0;
  await stream.followTurnEvents(async () => { attempts += 1; controller.abort(); throw new DOMException("aborted", "AbortError"); },
    { cursor: () => 0, finished: () => false }, controller.signal, async () => {});
  assert.equal(attempts, 1);
});
