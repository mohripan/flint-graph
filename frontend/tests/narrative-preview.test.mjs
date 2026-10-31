import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
const source = await readFile(new URL("../src/narrative/previewProtocol.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } });
const protocol = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
const nonce = "a".repeat(64), revision = "b6d5bdf9-e642-4158-9267-0d47c8977150", hash = "f".repeat(64);
test("preview hosting requires a separate host, exact origin, and secure remote transport", () => {
  assert.equal(protocol.previewOrigin("http://127.0.0.1:5192", "http://localhost:5173"), "http://127.0.0.1:5192");
  for (const child of ["http://localhost:5192", "https://x.test/path", "http://x.test", "https://u:p@x.test", "null"])
    assert.throws(() => protocol.previewOrigin(child, "http://localhost:5173"));
});
test("the preview channel rejects wrong-window, wrong-origin, wrong-nonce and unmatched acknowledgments", () => {
  const child = {}, origin = "http://127.0.0.1:5192";
  const context = { window: child, origin, nonce, revision, hash };
  const data = { protocol: "flint-preview", version: 1, nonce, type: "ready" };
  const event = { source: child, origin, data };
  assert.equal(protocol.acceptPreviewMessage(event, context, "waiting"), "ready");
  for (const changed of [{ source: {} }, { origin: "http://evil.test" }, { data: { ...data, nonce: "b".repeat(64) } },
    { data: { ...data, extra: "ignored?" } }, { data: { ...data, version: "1" } }])
    assert.equal(protocol.acceptPreviewMessage({ ...event, ...changed }, context, "waiting"), null);
  assert.equal(protocol.acceptPreviewMessage(event, context, "loading"), null);
  const loaded = { ...data, type: "loaded", revision_id: revision, content_hash: hash };
  assert.equal(protocol.acceptPreviewMessage({ ...event, data: loaded }, context, "loading"), "loaded");
  assert.equal(protocol.acceptPreviewMessage({ ...event, data: { ...loaded, content_hash: "0".repeat(64) } }, context, "loading"), null);
  assert.equal(protocol.acceptPreviewMessage({ ...event, data: loaded }, context, "waiting"), null);
});
test("v2 playtests check every declared asset's size and hash before loading", async () => {
  const bytes = text => new TextEncoder().encode(text).buffer;
  const hex = async data => protocol.sha256Hex(data);
  const dusk = bytes("dusk image"), type = bytes("font");
  const declared = {
    dusk: { kind: "image", path: "assets/dusk.png", sha256: await hex(dusk) },
    type: { kind: "font", path: "assets/type.ttf", sha256: await hex(type) },
  };
  assert.deepEqual(Object.keys(await protocol.checkedAssets(declared, { type, dusk })), ["dusk", "type"]);
  for (const fetched of [{ dusk }, { dusk, type, extra: dusk }, { dusk: type, type }, { dusk, type: new ArrayBuffer(8388609) }])
    await assert.rejects(protocol.checkedAssets(declared, fetched));
  await assert.rejects(protocol.checkedAssets({ ...declared, dusk: { ...declared.dusk, kind: "video" } }, { dusk, type }));
  assert.equal(protocol.storyAssets('{"schema_version":"1","assets":{}}'), null);
  assert.deepEqual(protocol.storyAssets(JSON.stringify({ schema_version: "2", assets: declared })), declared);
});
test("v1 revisions keep message version 1; v2 transfers its asset buffers", () => {
  const revision = { id: revision_id(), content_hash: hash, story_json: "{}", notices: "" };
  const v1 = protocol.snapshotMessage(nonce, revision, null);
  assert.equal(v1.message.version, 1);
  assert.equal("assets" in v1.message, false);
  assert.deepEqual(v1.transfer, []);
  const buffer = new ArrayBuffer(4);
  const v2 = protocol.snapshotMessage(nonce, revision, { dusk: buffer });
  assert.equal(v2.message.version, 2);
  assert.equal(v2.message.assets.dusk, buffer);
  assert.deepEqual(v2.transfer, [buffer]);
});
function revision_id() { return revision; }
