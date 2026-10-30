import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/narrative/assistantModel.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
const model = await import(`data:text/javascript;base64,${Buffer.from(outputText + "\n//# sourceURL=assistant-activity.js").toString("base64")}`);

let sequence = 0;
const at = second => new Date(Date.UTC(2026, 9, 31, 10, 0, second)).toISOString();
function event(kind, payload, { attempt = 1, second = sequence } = {}) {
  sequence += 1;
  return { turn_id: "t", sequence, attempt, kind, payload, created_at: at(second) };
}
function step(name, state, detail = {}, options) { return event("step", { name, state, ...detail }, options); }

test("events fold into ordered steps, per-call thinking and the streamed reply", () => {
  sequence = 0;
  const events = [
    step("start", "done"),
    step("context", "done", { scenes: 12, outlined: 10, omitted: 2, focus: "harbor", history: 2 }),
    step("model", "started", { call: 1, of: 3, provider: "ollama" }),
    event("thinking", { call: 1, text: "Oren needs " }),
    event("thinking", { call: 1, text: "a reason." }),
    event("text", { call: 1, text: "Here is " }),
    event("text", { call: 1, text: "a scene." }),
    step("drafting", "started", { call: 1 }),
    step("drafting", "progress", { call: 1, operations: 1 }),
    step("drafting", "progress", { call: 1, operations: 3 }),
    step("model", "done", { call: 1, output_tokens: 420 }),
    step("validating", "done", { call: 1, valid: false, problems: 2, codes: ["unknown_reference", "missing_end"] }),
    step("repair", "started", { call: 2, of: 3, problems: 2 }),
    step("model", "started", { call: 2, of: 3, provider: "ollama" }),
    event("text", { call: 2, text: "Fixed." }),
  ];
  const activity = model.foldEvents(model.emptyActivity(), events);
  assert.equal(activity.cursor, events.length);
  assert.equal(activity.call, 2);
  assert.equal(activity.calls[1].thinking, "Oren needs a reason.");
  assert.equal(activity.calls[1].text, "Here is a scene.");
  assert.equal(model.streamedReply(activity), "Fixed.");
  const views = model.activitySteps(activity, true);
  assert.deepEqual(views.map(view => [view.label, view.state]), [
    ["Read the story", "done"],
    ["Wrote a reply", "done"],
    ["Drafted changes", "done"],
    ["Found 2 problems", "failed"],
    ["Fixing 2 problems (attempt 2 of 3)", "done"],
    ["Rewriting the reply", "active"],
  ]);
  assert.equal(views[0].detail, "12 scenes, 2 left out to fit · focus harbor · 2 earlier messages");
  assert.equal(views[2].detail, "3 edits");
  assert.equal(views[3].detail, "unknown reference, missing end");
  // Replaying the same events (a resumed stream) changes nothing.
  assert.deepEqual(model.foldEvents(activity, events), activity);
});

test("a new attempt discards streamed text of the abandoned one and the status ends it", () => {
  sequence = 0;
  const first = [step("start", "done"), step("model", "started", { call: 1, of: 3 }), event("text", { call: 1, text: "Half a re" })];
  let activity = model.foldEvents(model.emptyActivity(), first);
  activity = model.foldEvents(activity, [
    step("start", "done", {}, { attempt: 2, second: 20 }),
    step("model", "started", { call: 1, of: 3 }, { attempt: 2, second: 21 }),
    event("text", { call: 1, text: "A full reply." }, { attempt: 2, second: 25 }),
    event("status", { status: "completed", error_code: null }, { attempt: 2, second: 34 }),
  ]);
  assert.equal(activity.attempt, 2);
  assert.equal(model.streamedReply(activity), "A full reply.");
  assert.equal(activity.status, "completed");
  assert.equal(model.activitySteps(activity, false)[0].label, "Reconnected and started again (attempt 2)");
  assert.equal(model.workedFor(activity), "Worked for 34 s");
  const steps = model.activitySteps(activity, false);
  assert.ok(steps.every(view => view.state !== "active"), "Nothing spins once the turn is over");
});

test("answers without proposals, truncation and long runs read naturally", () => {
  sequence = 0;
  const activity = model.foldEvents(model.emptyActivity(), [
    step("start", "done", {}, { second: 0 }),
    step("context", "done", { scenes: 1, outlined: 1, omitted: 0, focus: null, history: 0 }, { second: 0 }),
    step("model", "started", { call: 1, of: 3 }, { second: 1 }),
    step("truncated", "done", { kind: "thinking", call: 1 }, { second: 50 }),
    step("model", "done", { call: 1 }, { second: 70 }),
    step("validating", "done", { call: 1, valid: true, problems: 0, codes: [] }, { second: 70 }),
    event("status", { status: "failed", error_code: "provider_timeout" }, { second: 75 }),
  ]);
  const labels = model.activitySteps(activity, false).map(view => view.label);
  assert.deepEqual(labels, ["Read the story", "Wrote a reply", "Thinking was too long to keep in full", "Checked the changes against the story rules"]);
  assert.equal(model.activitySteps(activity, false)[0].detail, "1 scene");
  assert.equal(activity.errorCode, "provider_timeout");
  assert.equal(model.workedFor(activity), "Worked for 1 min 15 s");
  assert.equal(model.workedFor(model.emptyActivity()), "");
});

test("conversation titles come from the first message, bounded and on one line", () => {
  assert.equal(model.threadTitle("  Add a storm\nscene where Oren hides  "), "Add a storm scene where Oren hides");
  const long = model.threadTitle("word ".repeat(40));
  assert.ok(long.length <= 60 && long.endsWith("…"));
  assert.equal(model.threadTitle("   "), "Story chat");
});

test("a retried conversation creation keeps its key only for the same title", () => {
  let keys = 0;
  const key = () => `thread-${++keys}`;
  const first = model.prepareThread(null, "Add a storm", key);
  assert.deepEqual(first, { title: "Add a storm", key: "thread-1" });
  assert.equal(model.prepareThread(first, "Add a storm", key), first);
  assert.deepEqual(model.prepareThread(first, "Add a flood", key), { title: "Add a flood", key: "thread-2" });
});
