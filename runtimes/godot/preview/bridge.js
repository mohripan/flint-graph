/* SPDX-License-Identifier: MIT. Trusted adapter; creator content is never code. */
"use strict";
(() => {
  const parentOrigin = __TRUSTED_PARENT_ORIGIN__;
  const nonce = location.hash.slice(1);
  const validNonce = /^[0-9a-f]{64}$/.test(nonce);
  const status = document.getElementById("status");
  let phase = "starting", callback = null, identity = null;
  const base = type => ({ protocol: "flint-preview", version: 1, nonce, type });
  const send = (type, extra = {}) => {
    if (validNonce && window.parent !== window) window.parent.postMessage({ ...base(type), ...extra }, parentOrigin);
  };
  const exact = (value, keys) => value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
  const bounded = (value, cap) => typeof value === "string" && value.length <= cap
    && new TextEncoder().encode(value).length <= cap;
  window.addEventListener("message", event => {
    if (!validNonce || phase !== "waiting" || event.source !== window.parent || event.origin !== parentOrigin) return;
    const data = event.data;
    if (!exact(data, ["protocol", "version", "nonce", "type", "revision_id", "content_hash", "story_json", "notices"])
      || data.protocol !== "flint-preview" || data.version !== 1 || data.nonce !== nonce || data.type !== "load-snapshot"
      || typeof data.revision_id !== "string" || !/^[0-9a-f-]{36}$/.test(data.revision_id)
      || typeof data.content_hash !== "string" || !/^[0-9a-f]{64}$/.test(data.content_hash)
      || !bounded(data.story_json, 5242880) || !bounded(data.notices, 1048576)) return;
    phase = "loading";
    identity = { revision_id: data.revision_id, content_hash: data.content_hash };
    callback(JSON.stringify({ ...identity, story_json: data.story_json, notices: data.notices }));
    callback = null;
  });
  window.addEventListener("keydown", event => {
    if (event.key === "Escape") { event.preventDefault(); event.stopImmediatePropagation(); send("close"); }
  }, true);
  window.FlintPreview = Object.freeze({
    install(fn) {
      if (phase !== "starting" || !validNonce || window.parent === window) return;
      callback = fn; phase = "waiting"; status.textContent = "Waiting for a saved revision…"; send("ready");
    },
    loaded(revision, hash) {
      if (phase !== "loading" || revision !== identity.revision_id || hash !== identity.content_hash) return;
      phase = "loaded"; status.hidden = true; send("loaded", identity);
    },
    failed(revision, hash) {
      if (phase !== "loading" || revision !== identity.revision_id || hash !== identity.content_hash) return;
      phase = "error"; status.textContent = "The saved snapshot could not be validated."; send("error", identity);
    },
  });
  if (!validNonce || window.parent === window) { status.textContent = "Open playtest from the studio."; return; }
  const config = JSON.parse(document.getElementById("godot-config").textContent);
  config.canvas = document.getElementById("canvas");
  config.persistentPaths = []; // No private progress is persisted by this preview.
  const engine = new Engine(config);
  engine.startGame().catch(() => { status.textContent = "The story player could not start. Close playtest and retry."; });
})();
