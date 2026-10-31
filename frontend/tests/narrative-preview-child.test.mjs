import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
const source = await readFile(new URL("../../runtimes/godot/preview/bridge.js", import.meta.url), "utf8");

test("the trusted child accepts one bounded snapshot only from its configured parent window and nonce", () => {
  const nonce = "a".repeat(64), origin = "http://localhost:5173", listeners = new Map(), sent = [];
  const status = { textContent: "", hidden: false };
  const parent = { postMessage: (value, target) => sent.push({ value, target }) };
  const child = { parent, addEventListener: (type, fn) => listeners.set(type, fn) };
  const context = { window: child, location: { hash: "#" + nonce }, TextEncoder,
    document: { getElementById: id => id === "godot-config" ? { textContent: "{}" } : status },
    Engine: class { startGame() { return Promise.resolve(); } } };
  vm.runInNewContext(source.replace("__TRUSTED_PARENT_ORIGIN__", JSON.stringify(origin)), context);
  const delivered = [];
  child.FlintPreview.install(value => delivered.push(JSON.parse(value)));
  assert.equal(sent.length, 1);
  assert.equal(sent[0].target, origin);
  assert.equal(sent[0].value.type, "ready");
  const payload = { protocol: "flint-preview", version: 1, nonce, type: "load-snapshot",
    revision_id: "b6d5bdf9-e642-4158-9267-0d47c8977150", content_hash: "f".repeat(64), story_json: "{}", notices: "" };
  const message = listeners.get("message");
  for (const event of [{ source: {}, origin, data: payload }, { source: parent, origin: "http://evil.test", data: payload },
    ...[{ ...payload, nonce: "b".repeat(64) }, { ...payload, token: "never-send" }, { ...payload, notices: "x".repeat(1048577) },
      { ...payload, version: "1" }].map(data => ({ source: parent, origin, data }))]) message(event);
  assert.equal(delivered.length, 0);
  message({ source: parent, origin, data: payload });
  message({ source: parent, origin, data: payload });
  assert.equal(delivered.length, 1);
  assert.deepEqual(Object.keys(delivered[0]).sort(), ["assets", "content_hash", "notices", "revision_id", "story_json"]);
  assert.deepEqual(delivered[0].assets, []);
  child.FlintPreview.loaded(payload.revision_id, "0".repeat(64));
  assert.equal(sent.length, 1);
  child.FlintPreview.loaded(payload.revision_id, payload.content_hash);
  assert.equal(sent.length, 2);
  assert.equal(sent[1].value.type, "loaded");
  assert.equal(status.hidden, true);
  child.FlintPreview.failed(payload.revision_id, payload.content_hash);
  assert.equal(sent.length, 2);
});

test("story format 2 snapshots bring bounded transferred assets that the engine pulls once each", () => {
  const nonce = "c".repeat(64), origin = "http://localhost:5173", listeners = new Map(), copies = [];
  const parent = { postMessage: () => {} };
  const child = { parent, addEventListener: (type, fn) => listeners.set(type, fn) };
  const context = { window: child, location: { hash: "#" + nonce }, TextEncoder,
    document: { getElementById: id => id === "godot-config" ? { textContent: "{}" } : { textContent: "" } },
    Engine: class { startGame() { return Promise.resolve(); } copyToFS(path, buffer) { copies.push({ path, size: buffer.byteLength }); } } };
  vm.runInNewContext(source.replace("__TRUSTED_PARENT_ORIGIN__", JSON.stringify(origin)), context);
  const delivered = [];
  child.FlintPreview.install(value => delivered.push(JSON.parse(value)));
  const story = JSON.stringify({ schema_version: "2", assets: { dusk: { kind: "image" }, type: { kind: "font" } } });
  // Structured clone creates the message objects in the child's own realm.
  const assets = sizes => vm.runInContext(`({ type: new ArrayBuffer(${sizes[1]}), dusk: new ArrayBuffer(${sizes[0]}) })`, context);
  const payload = { protocol: "flint-preview", version: 2, nonce, type: "load-snapshot",
    revision_id: "b6d5bdf9-e642-4158-9267-0d47c8977150", content_hash: "f".repeat(64), story_json: story, notices: "" };
  const message = listeners.get("message");
  for (const data of [
    { ...payload, assets: assets([4, 8388609]) },  // A font over its 8 MiB cap.
    { ...payload, assets: assets([10485761, 4]) },  // An image over its 10 MiB cap.
    { ...payload, assets: vm.runInContext("({ dusk: new ArrayBuffer(4) })", context) },
    { ...payload, assets: vm.runInContext("({ dusk: new ArrayBuffer(4), type: 'not bytes' })", context) },
    { ...payload, assets: { dusk: new ArrayBuffer(4), type: new ArrayBuffer(4) } },  // Not a cloned object.
    { ...payload, version: 1, assets: assets([4, 4]) },
    { ...payload },
  ]) message({ source: parent, origin, data });
  assert.equal(delivered.length, 0);
  message({ source: parent, origin, data: { ...payload, assets: assets([5, 7]) } });
  assert.equal(delivered.length, 1);
  assert.deepEqual(delivered[0].assets, ["dusk", "type"]);
  assert.equal(child.FlintPreview.take(2), false);
  assert.equal(child.FlintPreview.take(0), true);
  assert.equal(child.FlintPreview.take(0), false);
  assert.equal(child.FlintPreview.take(1), true);
  assert.deepEqual(copies, [{ path: "/tmp/flint-preview-asset", size: 5 }, { path: "/tmp/flint-preview-asset", size: 7 }]);
});
