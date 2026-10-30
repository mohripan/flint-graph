import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
const { api, setAccessTokenProvider } = await import(`data:text/javascript;base64,${Buffer.from(outputText + "\n//# sourceURL=layout-api-test.js").toString("base64")}`);

test("scene layout reads are uncached and saves carry the base version", async () => {
  const original = globalThis.fetch, calls = [];
  setAccessTokenProvider(async () => "fixture-access-token");
  globalThis.fetch = async (path, init) => { calls.push({ path, init }); return new Response("{}", { status: 200 }); };
  try {
    const { signal } = new AbortController();
    const items = [{ type: "group", id: "act_one", name: "Act one", collapsed: false, items: [{ type: "scene", id: "opening" }] }];
    await api.getNarrativeLayout("workspace", "project", signal);
    await api.saveNarrativeLayout("workspace", "project", 3, items, signal);
    assert.deepEqual(calls.map(({ path, init }) => [init.method ?? "GET", path, init.cache ?? null]), [
      ["GET", "/v1/narrative/projects/project/layout", "no-store"],
      ["PUT", "/v1/narrative/projects/project/layout", null],
    ]);
    assert.deepEqual(JSON.parse(calls[1].init.body), { base_version: 3, items });
    assert.ok(calls.every(({ init }) => init.signal === signal && init.headers["X-Tenant-ID"] === "workspace"
      && init.headers.Authorization === "Bearer fixture-access-token"));
  } finally { globalThis.fetch = original; setAccessTokenProvider(null); }
});
