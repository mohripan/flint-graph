import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/narrative/draftState.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } });
const draft = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

test("unchanged lost-response retries preserve identity; new work receives a fresh key", () => {
  let number = 0;
  const key = () => `request-${++number}`;
  const first = draft.prepareSave(null, "base-a", "original source", "notices", key);
  assert.strictEqual(draft.prepareSave(first, "base-a", "original source", "notices", key), first);
  const edited = draft.prepareSave(first, "base-a", "changed source", "notices", key);
  assert.equal(edited.idempotency_key, "request-2");
  assert.equal(first.story_json, "original source");
  const rebased = draft.prepareSave(edited, "base-b", "changed source", "notices", key);
  assert.equal(rebased.idempotency_key, "request-3");
});

const project = { id: "project-a", tenant_id: "workspace-a", head_revision_id: "revision-a" };
const revision = { id: "revision-a", project_id: "project-a", tenant_id: "workspace-a",
  story_json: "original", notices: "private notices" };

test("a late project load or save cannot revive content after access loss or navigation", () => {
  let state = draft.initialDraftState();
  state = draft.draftReducer(state, { type: "load", generation: 1 });
  state = draft.draftReducer(state, { type: "loaded", generation: 1, project, revision });
  assert.equal(state.source, "original");
  state = draft.draftReducer(state, { type: "clear", generation: 2, message: "Access changed." });
  state = draft.draftReducer(state, { type: "loaded", generation: 1, project, revision });
  state = draft.draftReducer(state, { type: "saved", generation: 1, revision });
  assert.equal(state.source, "");
  assert.equal(state.notices, "");
  assert.equal(state.project, null);
  assert.equal(state.error, "Access changed.");
});

test("a conflict retains the visible draft while a successful acknowledgment sets a new base", () => {
  let state = draft.draftReducer(draft.initialDraftState(), { type: "load", generation: 1 });
  state = draft.draftReducer(state, { type: "loaded", generation: 1, project, revision });
  state = draft.draftReducer(state, { type: "edit", source: "new writing" });
  const request = draft.prepareSave(null, revision.id, state.source, state.notices, () => "key");
  state = draft.draftReducer(state, { type: "saving", generation: 1, request });
  state = draft.draftReducer(state, { type: "failed", generation: 1, message: "Saved a conflict copy.",
    conflict: { revisionId: "conflict", headId: "current" } });
  assert.equal(state.source, "new writing");
  assert.equal(state.revision.id, "revision-a");
  assert.equal(state.request.idempotency_key, "key");
  state = draft.draftReducer(state, { type: "saved", generation: 1,
    revision: { ...revision, id: "revision-b", story_json: "new writing" } });
  assert.equal(state.revision.id, "revision-b");
  assert.equal(state.project.head_revision_id, "revision-b");
  assert.equal(state.request, null);
  assert.equal(state.conflict, null);
});
