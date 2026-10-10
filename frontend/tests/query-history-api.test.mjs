import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } });
const { api } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

test("question history sends bounded pagination and literal search through the public API", async () => {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (path, init) => {
    calls.push({ path, init });
    return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
  };
  try {
    const controller = new AbortController();
    await api.listQueryRuns("tenant-a", { limit: 25, beforeId: "cursor-id", query: " revenue %_ / FY ", signal: controller.signal });
    const url = new URL(calls[0].path, "http://test");
    assert.equal(url.pathname, "/v1/query-runs");
    assert.equal(url.searchParams.get("limit"), "25");
    assert.equal(url.searchParams.get("before_id"), "cursor-id");
    assert.equal(url.searchParams.get("q"), "revenue %_ / FY");
    assert.equal(calls[0].init.headers["X-Tenant-ID"], "tenant-a");
    assert.equal(calls[0].init.signal, controller.signal);
    assert.equal(calls[0].init.method, undefined);
  } finally {
    globalThis.fetch = original;
  }
});

test("reopening a saved run and provenance is read-only and cancellable", async () => {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (path, init) => {
    calls.push({ path, init });
    return new Response("{}", { status: 200 });
  };
  try {
    const controller = new AbortController();
    await api.getQueryRun("tenant-a", "run-id", controller.signal);
    await api.getAnswerProvenance("tenant-a", "run-id", controller.signal);
    assert.deepEqual(calls.map((call) => call.path), ["/v1/query-runs/run-id", "/v1/query-runs/run-id/provenance"]);
    assert.ok(calls.every((call) => call.init.signal === controller.signal && !call.init.method));
  } finally {
    globalThis.fetch = original;
  }
});
