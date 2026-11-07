import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/narrative/assistantActions.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
const model = await import(`data:text/javascript;base64,${Buffer.from(outputText + "\n//# sourceURL=assistant-actions.js").toString("base64")}`);

const job = (status, progress = 0, extra = {}) => ({
  id: "job", status, progress, count: 4, error_code: null, created_at: "2026-11-06", purpose: "background", assets: [], ...extra,
});
const action = (status, extra = {}) => ({
  index: 0, op: "generate_backgrounds", label: "backgrounds", status, needs_accept: false,
  error_code: null, detail: null, image_job: null, voice_job: null, ...extra,
});

test("the page keeps watching only while something can still change", () => {
  assert.equal(model.actionWatching(action("pending")), true);
  assert.equal(model.actionWatching(action("started", { image_job: job("running") })), true);
  assert.equal(model.actionWatching(action("started", { voice_job: job("queued") })), true);
  assert.equal(model.actionWatching(action("started", { image_job: job("completed") })), false);
  assert.equal(model.actionWatching(action("finished", { image_job: job("completed") })), false);
  for (const status of ["offered", "declined", "blocked", "skipped"]) {
    assert.equal(model.actionWatching(action(status)), false, status);
  }
});

test("a slow read cannot undo a start, progress or a finish", () => {
  const started = action("started", { image_job: job("running", 2) });
  assert.equal(model.mergeAction(started, action("pending")), started, "a stale pending keeps the job");
  const done = action("finished", { image_job: job("completed", 4) });
  assert.equal(model.mergeAction(done, started), done);
  assert.equal(model.mergeAction(started, done), done);
  const behind = model.mergeAction(started, action("started", { image_job: job("running", 1) }));
  assert.equal(behind.image_job.progress, 2);
  assert.equal(model.mergeAction(action("blocked"), action("pending")).status, "pending", "a retry moves on");
  assert.equal(model.mergeAction(undefined, started), started);
  assert.equal(model.mergeAction(action("offered"), action("declined")).status, "declined");
  assert.equal(model.mergeAction(action("declined"), action("offered")).status, "declined", "a stale read cannot undo Cancel");
  assert.equal(model.mergeAction(started, action("declined")), started, "or a change of mind");
});

test("each state tells the creator what is happening in plain words", () => {
  assert.deepEqual(model.actionState(action("declined")), { text: "Cancelled. Nothing was generated.", tone: "muted" });
  assert.deepEqual(model.actionState(action("offered", { needs_accept: true })),
    { text: "Accept the proposal before generating this.", tone: "muted" });
  assert.deepEqual(model.actionState(action("pending")), { text: "Waiting for a free slot…", tone: "muted" });
  assert.deepEqual(model.actionState(action("blocked", { detail: "Approve a picture of Mira first." })),
    { text: "Approve a picture of Mira first.", tone: "bad" });
  assert.equal(model.actionState(action("started", { image_job: job("running", 1) })).text, "Generating 1 of 4…");
  assert.equal(model.actionState(action("started", { image_job: job("queued") })).text, "Queued…");
  assert.equal(model.actionState(action("started")).text, "Starting…");
  assert.equal(model.actionState(action("finished", { image_job: job("cancelled") })).text, "Stopped.");
  assert.deepEqual(model.actionState(action("finished", { image_job: job("completed", 4, { assets: [{ id: "a" }, { id: "b" }] }) })),
    { text: "2 to review.", tone: "good" });
  assert.deepEqual(model.actionState(action("offered")), { text: "", tone: "muted" });
});

test("a failed job says why, and a busy GPU reads as temporary", () => {
  const failed = model.actionState(action("finished", { image_job: job("failed", 0, { error_code: "gpu_busy" }) }));
  assert.equal(failed.tone, "bad");
  assert.match(failed.text, /GPU/);
  const other = model.actionState(action("finished", { voice_job: job("failed", 0, { error_code: "whatever" }) }));
  assert.match(other.text, /failed/i);
});

const quote = {
  kind: "Background", title: "rainy street", facts: [{ icon: "model", text: "Animagine XL 4.0" }],
  parts: [{ item: "image.standard", quantity: 4 }], button: "Generate backgrounds", opens: "assets",
};

test("a card asks before anything runs, and stays out of the way once answered", () => {
  for (const status of ["offered", "blocked"]) {
    assert.equal(model.actionShowsCard(action(status, { quote }), false), true, status);
  }
  assert.equal(model.actionShowsCard(action("offered", { quote, needs_accept: true }), false), true, "it can explain what it needs");
  assert.equal(model.actionShowsCard(action("declined", { quote }), false), false);
  assert.equal(model.actionShowsCard(action("declined", { quote }), true), true, "shown again on request");
  assert.equal(model.actionShowsCard(action("offered"), false), false, "no card without a quote from the server");
  for (const status of ["pending", "started", "finished", "skipped"]) {
    assert.equal(model.actionShowsCard(action(status, { quote }), true), false, status);
  }
});

test("the button says what will be made, or that this is another try", () => {
  assert.equal(model.cardLabel(action("offered"), quote), "Generate backgrounds");
  assert.equal(model.cardLabel(action("declined"), quote), "Generate backgrounds");
  assert.equal(model.cardLabel(action("blocked"), quote), "Try again");
  assert.deepEqual(model.quoteParts(quote), [["image.standard", 4]]);
});

const story = {
  characters: { mira: { name: "Mira", sprites: { neutral: "mira_neutral" } }, ren: { name: "Ren" } },
  assets: { mira_neutral: { kind: "image", path: "assets/mira_neutral.png", sha256: "s1" }, clip: { kind: "audio", path: "assets/clip.wav", sha256: "s9" } },
  nodes: { hello: { type: "line", speaker: "mira", text: "Hi.", next: "e", voice: { mode: "full", audio: "clip" } }, e: { type: "end", text: "", ending: "x" } },
};
const picture = (extra = {}) => ({ id: "a", sha256: "s2", name: "Mira 1", provenance: {}, ...extra });

test("a sprite candidate can go on stage, and says so once it is", () => {
  const sprite = { purpose: "character_portrait", transparent: true, character_id: "ren" };
  const use = model.imageUse(sprite, picture(), story);
  assert.deepEqual(use, { kind: "sprite", character: "ren", expression: "default", label: "Use on stage", done: false });
  assert.equal(model.imageUse({ ...sprite, character_id: "mira" }, picture({ sha256: "s1" }), story).done, true);
  assert.equal(model.imageUse({ ...sprite, character_id: "mira" }, picture(), story).expression, null,
    "a character who already has a neutral sprite gets a new expression name");
});

test("an expression candidate replaces that expression", () => {
  const made = { purpose: "character_expression", character_id: "mira", expressions: ["happy"] };
  const use = model.imageUse(made, picture({ provenance: { expression: "Very Happy" } }), story);
  assert.deepEqual(use, { kind: "sprite", character: "mira", expression: "very_happy", label: "Use as very happy", done: false });
});

test("pictures that are not stage sprites are only approved", () => {
  assert.equal(model.imageUse({ purpose: "background", character_id: null }, picture(), story), null);
  assert.equal(model.imageUse({ purpose: "scene_art", character_id: "mira" }, picture(), story), null);
  assert.equal(model.imageUse({ purpose: "character_portrait", transparent: false, character_id: "mira" }, picture(), story), null);
});

test("a voice clip can go on its line, and says so once it is", () => {
  const clip = (sha256, node_id = "hello") => ({ id: "c", sha256, provenance: { node_id, mode: "full" } });
  assert.deepEqual(model.clipUse(clip("s3"), story), { node: "hello", label: "Use on the line", done: false });
  assert.equal(model.clipUse(clip("s9"), story).done, true);
  assert.equal(model.clipUse(clip("s3", "gone"), story), null, "the line no longer exists");
});

test("a child session reads as a conversation, not a job", () => {
  const session = { id: "t", title: "Create the cast" };
  const started = action("started", { op: "start_child_session", child_thread: session });
  assert.equal(model.actionState(started).text, "Working on it…");
  assert.equal(model.actionWatching(started), true);
  const done = action("finished", { op: "start_child_session", child_thread: session });
  assert.deepEqual(model.actionState(done), { text: "It has replied. Open it to review.", tone: "good" });
  assert.equal(model.actionWatching(done), false);
  assert.equal(model.cardLabel(action("offered", { op: "start_child_session" }), { button: "Start session" }), "Start session");
});
