import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/narrative/assistantModel.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
const model = await import(`data:text/javascript;base64,${Buffer.from(outputText + "\n//# sourceURL=assistant-model.js").toString("base64")}`);

const story = {
  title: "The Harbor Bell", entry: "opening",
  characters: { oren: { name: "Oren" } }, variables: { courage: { type: "int", initial: 0 } },
  nodes: { opening: { type: "line", text: "Fog.", next: "ending" }, ending: { type: "end", text: "Done.", ending: "done" } },
};

test("a lost send keeps its key only for the same request, revision and focus", () => {
  let keys = 0;
  const key = () => `key-${++keys}`;
  const first = model.prepareTurn(null, "Add a storm.", "rev-1", "opening", key);
  assert.equal(model.prepareTurn(first, "Add a storm.", "rev-1", "opening", key), first);
  assert.equal(model.prepareTurn(first, "Add a storm!", "rev-1", "opening", key).idempotency_key, "key-2");
  assert.equal(model.prepareTurn(first, "Add a storm.", "rev-2", "opening", key).idempotency_key, "key-3");
  assert.equal(model.prepareTurn(first, "Add a storm.", "rev-1", null, key).idempotency_key, "key-4");
});

test("sending needs write access, a saved draft, text and no reply in progress", () => {
  const ready = { canWrite: true, dirty: false, saving: false, sending: false, active: false, text: "Add a storm." };
  assert.equal(model.sendBlocker(ready), null);
  assert.match(model.sendBlocker({ ...ready, canWrite: false }), /Viewers/);
  assert.match(model.sendBlocker({ ...ready, dirty: true }), /Save your changes/);
  assert.match(model.sendBlocker({ ...ready, active: true }), /current reply/);
  assert.match(model.sendBlocker({ ...ready, text: "   " }), /Describe/);
  assert.match(model.sendBlocker({ ...ready, text: "x".repeat(8001) }), /8,000/);
});

test("polled turns merge by id, never regress from terminal states and stay in order", () => {
  const queued = { id: "a", sequence: 1, status: "queued", updated_at: "2026-10-31T00:00:01Z", proposal: null };
  const done = { ...queued, status: "completed", updated_at: "2026-10-31T00:00:09Z", proposal: { id: "p", status: "ready" } };
  const second = { id: "b", sequence: 2, status: "queued", updated_at: "2026-10-31T00:00:10Z", proposal: null };
  assert.deepEqual(model.mergeTurns([queued], [second, done]).map(row => [row.id, row.status]), [["a", "completed"], ["b", "queued"]]);
  assert.deepEqual(model.mergeTurns([done], [queued]), [done], "A late queued snapshot cannot undo completion");
  const accepted = { ...done, proposal: { id: "p", status: "accepted" } };
  assert.deepEqual(model.mergeTurns([accepted], [done]), [accepted], "A decided proposal stays decided");
  assert.equal(model.activeTurn([done, second]), true);
  assert.equal(model.activeTurn([done]), false);
});

test("proposal changes are described against the saved story in plain language", () => {
  const changes = model.proposalChanges(story, [
    { op: "upsert_node", id: "storm", node: { type: "line", text: "Thunder rolls over the harbor.", next: "ending" } },
    { op: "upsert_node", id: "opening", node: { type: "line", text: "Fog and wind.", next: "storm" } },
    { op: "delete_node", id: "ending" },
    { op: "upsert_character", id: "mira", name: "Mira" },
    { op: "upsert_variable", id: "courage", declaration: { type: "int", initial: 1 } },
    { op: "set_entry", id: "storm" },
    { op: "set_title", title: "Storm Bell" },
  ]);
  assert.deepEqual(changes.map(row => [row.kind, row.target, row.label]), [
    ["added", "nodes.storm", "Scene storm"],
    ["changed", "nodes.opening", "Scene opening"],
    ["removed", "nodes.ending", "Scene ending"],
    ["added", "characters.mira", "Character Mira"],
    ["changed", "variables.courage", "State courage"],
    ["changed", "entry", "Start scene → storm"],
    ["changed", "title", "Title → Storm Bell"],
  ]);
  assert.equal(changes[0].after, "Thunder rolls over the harbor.");
  assert.equal(changes[1].before, "Fog.");
  assert.equal(changes[2].before, "Done.");
  assert.deepEqual(model.proposalChanges(null, []), []);
});

test("turn and failure copy is human and never shows raw codes", () => {
  assert.equal(model.turnStatus({ status: "queued", cancel_requested: false }), "Waiting for the assistant…");
  assert.equal(model.turnStatus({ status: "running", cancel_requested: false }), "Writing a reply…");
  assert.equal(model.turnStatus({ status: "running", cancel_requested: true }), "Stopping…");
  assert.match(model.assistantError("provider_unavailable"), /Ollama/);
  assert.match(model.assistantError("provider_timeout"), /too long/);
  assert.doesNotMatch(model.assistantError("something_new"), /something_new/);
  assert.equal(model.proposalStatus("invalid"), "Can't be used");
  assert.equal(model.proposalStatus("ready"), "Ready to review");
});
