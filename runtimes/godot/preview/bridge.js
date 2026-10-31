/* SPDX-License-Identifier: MIT. Trusted adapter; creator content is never code. */
"use strict";
(() => {
  const parentOrigin = __TRUSTED_PARENT_ORIGIN__;
  const nonce = location.hash.slice(1);
  const validNonce = /^[0-9a-f]{64}$/.test(nonce);
  const status = document.getElementById("status");
  // Story format 2 (ADR 0040) brings image and font bytes as transferred ArrayBuffers.
  const STAGED = "/tmp/flint-preview-asset";
  const CAPS = { image: 10485760, font: 8388608 };
  const TOTAL = 104857600;
  let phase = "starting", callback = null, identity = null, engine = null, buffers = [];
  let galleryOpen = false;
  const base = type => ({ protocol: "flint-preview", version: 1, nonce, type });
  const send = (type, extra = {}) => {
    if (validNonce && window.parent !== window) window.parent.postMessage({ ...base(type), ...extra }, parentOrigin);
  };
  const exact = (value, keys) => value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
  const bounded = (value, cap) => typeof value === "string" && value.length <= cap
    && new TextEncoder().encode(value).length <= cap;
  const plain = value => value && typeof value === "object" && Object.getPrototypeOf(value) === Object.prototype;
  // Bounds the bytes handed to the engine; the engine's validator checks every hash.
  const assetList = (assets, storyJson) => {
    if (!plain(assets)) return null;
    let kinds;
    try { kinds = JSON.parse(storyJson).assets; } catch { return null; }
    if (!plain(kinds)) return null;
    const ids = Object.keys(assets).sort();
    if (ids.length > 256 || ids.length !== Object.keys(kinds).length) return null;
    let total = 0;
    for (const id of ids) {
      const data = assets[id], cap = plain(kinds[id]) ? CAPS[kinds[id].kind] : undefined;
      if (!/^[a-z][a-z0-9_-]{0,63}$/.test(id) || !(data instanceof ArrayBuffer) || !cap || data.byteLength > cap) return null;
      total += data.byteLength;
      if (total > TOTAL) return null;
    }
    return ids;
  };
  window.addEventListener("message", event => {
    if (!validNonce || phase !== "waiting" || event.source !== window.parent || event.origin !== parentOrigin) return;
    const data = event.data;
    const fields = ["protocol", "version", "nonce", "type", "revision_id", "content_hash", "story_json", "notices"];
    const v2 = data && data.version === 2;
    if (!exact(data, v2 ? [...fields, "assets"] : fields)
      || data.protocol !== "flint-preview" || (data.version !== 1 && !v2) || data.nonce !== nonce || data.type !== "load-snapshot"
      || typeof data.revision_id !== "string" || !/^[0-9a-f-]{36}$/.test(data.revision_id)
      || typeof data.content_hash !== "string" || !/^[0-9a-f]{64}$/.test(data.content_hash)
      || !bounded(data.story_json, 5242880) || !bounded(data.notices, 1048576)) return;
    const ids = v2 ? assetList(data.assets, data.story_json) : [];
    if (ids === null) return;
    phase = "loading";
    identity = { revision_id: data.revision_id, content_hash: data.content_hash };
    buffers = ids.map(id => data.assets[id]);
    callback(JSON.stringify({ ...identity, story_json: data.story_json, notices: data.notices, assets: ids }));
    callback = null;
  });
  window.addEventListener("keydown", event => {
    // Let the engine close its gallery first. The next Escape closes the playtest.
    if (event.key === "Escape" && !galleryOpen) { event.preventDefault(); event.stopImmediatePropagation(); send("close"); }
  }, true);
  window.FlintPreview = Object.freeze({
    gallery(open) {
      if (phase === "loaded" && typeof open === "boolean") galleryOpen = open;
    },
    install(fn) {
      if (phase !== "starting" || !validNonce || window.parent === window) return;
      callback = fn; phase = "waiting"; status.textContent = "Waiting for a saved revision…"; send("ready");
    },
    // The engine pulls one asset at a time; each buffer is handed over once.
    take(index) {
      if (phase !== "loading" || !Number.isInteger(index) || !buffers[index] || !engine) return false;
      try { engine.copyToFS(STAGED, buffers[index]); } catch { return false; }
      buffers[index] = null;
      return true;
    },
    loaded(revision, hash) {
      if (phase !== "loading" || revision !== identity.revision_id || hash !== identity.content_hash) return;
      phase = "loaded"; buffers = []; status.hidden = true; send("loaded", identity);
    },
    failed(revision, hash) {
      if (phase !== "loading" || revision !== identity.revision_id || hash !== identity.content_hash) return;
      phase = "error"; buffers = []; status.textContent = "The saved snapshot could not be validated."; send("error", identity);
    },
  });
  if (!validNonce || window.parent === window) { status.textContent = "Open playtest from the studio."; return; }
  const config = JSON.parse(document.getElementById("godot-config").textContent);
  config.canvas = document.getElementById("canvas");
  config.persistentPaths = []; // No private progress is persisted by this preview.
  engine = new Engine(config);
  engine.startGame().catch(() => { status.textContent = "The story player could not start. Close playtest and retry."; });
})();
