import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function load(path) {
  const source = await readFile(new URL(path, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } });
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
}

const images = await load("../src/narrative/assistantImages.ts");
const library = await load("../src/narrative/assistantLibrary.ts");
const { api } = await load("../src/lib/api.ts");

test("a large screenshot is scaled to fit and keeps its shape, and a small one is left alone", () => {
  assert.deepEqual(images.scaledSize(3200, 1800, 1600), { width: 1600, height: 900 });
  assert.deepEqual(images.scaledSize(1000, 2000, 1600), { width: 800, height: 1600 });
  assert.deepEqual(images.scaledSize(800, 600, 1600), { width: 800, height: 600 });
  assert.deepEqual(images.scaledSize(4000, 1, 1600), { width: 1600, height: 1 });
});

test("only pictures are taken from a paste or a drop, so pasting text still pastes text", () => {
  const files = [{ type: "image/png", name: "a" }, { type: "text/plain", name: "b" }, { type: "image/jpeg", name: "c" }];
  assert.deepEqual(images.imagesIn({ files }).map(file => file.name), ["a", "c"]);
  assert.deepEqual(images.imagesIn({ files: [] }), []);
  assert.deepEqual(images.imagesIn(null), []);
});

test("a message takes up to its limit of pictures and says so about the rest", () => {
  assert.deepEqual(images.roomFor(2, 0, 3), { take: 2, note: null });
  assert.deepEqual(images.roomFor(2, 2, 3), { take: 1, note: "You can attach up to 3 pictures to a message." });
  assert.equal(images.roomFor(1, 3, 3).take, 0);
  assert.equal(images.imageCount([{ kind: "image" }, { kind: "asset" }, { kind: "image" }]), 2);
});

test("a picture is called a screenshot, and removing its chip removes it", () => {
  const shot = { kind: "image", id: "a", name: "Screenshot", asset_kind: null };
  assert.equal(library.attachmentKind(shot), "Picture");
  assert.deepEqual(library.toggleAttachment([shot], shot), []);
});

test("pictures go to their project's assistant, scoped to the workspace", async () => {
  const original = globalThis.fetch, calls = [];
  globalThis.fetch = async (path, init) => {
    calls.push({ path, init });
    if (path.endsWith("/capabilities")) return new Response(JSON.stringify({ images: true, max_images: 3 }));
    if (init?.method === "POST") return new Response(JSON.stringify({ id: "i", width: 2, height: 2 }), { status: 201 });
    return new Response(new Blob(["x"], { type: "image/png" }));
  };
  try {
    assert.equal((await api.assistantCapabilities("workspace", "project")).images, true);
    assert.equal((await api.uploadAssistantImage("workspace", "project", new Blob(["x"], { type: "image/png" }))).id, "i");
    assert.equal((await api.getAssistantImage("workspace", "project", "a/b")).type, "image/png");
  } finally { globalThis.fetch = original; }
  assert.equal(calls[0].path, "/v1/narrative/projects/project/assistant/capabilities");
  assert.equal(calls[1].path, "/v1/narrative/projects/project/assistant/images");
  assert.ok(calls[1].init.body.get("file"));
  assert.equal(calls[2].path, "/v1/narrative/projects/project/assistant/images/a%2Fb");
  for (const call of calls) assert.equal(call.init.headers["X-Tenant-ID"], "workspace");
});
