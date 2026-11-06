import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/narrative/assistantLog.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
const log = await import(`data:text/javascript;base64,${Buffer.from(outputText + "\n//# sourceURL=assistant-log.js").toString("base64")}`);

const event = (sequence, kind, payload = {}) => ({
  thread_id: "thread", sequence, kind, payload, actor_user_id: null, created_at: "2026-11-06T10:00:00Z",
});

test("merging pages keeps one ordered copy of each event, so a repeated poll is harmless", () => {
  const first = log.mergeLog([], [event(2, "turn.requested"), event(1, "thread.created")]);
  assert.deepEqual(first.map(item => item.sequence), [1, 2]);
  const second = log.mergeLog(first, [event(2, "turn.requested"), event(3, "turn.completed")]);
  assert.deepEqual(second.map(item => item.sequence), [1, 2, 3]);
  assert.equal(log.mergeLog(second, []), second, "nothing new keeps the same array");
});

test("each lifecycle event reads as one plain line", () => {
  const lines = log.logLines([
    event(1, "thread.created", { title: "Storm ideas" }),
    event(2, "turn.requested", { request: "Add a storm." }),
    event(3, "turn.completed", { reply: "Here it is." }),
    event(4, "proposal.created", { summary: "Add a storm scene", status: "ready" }),
    event(5, "proposal.accepted", { summary: "Add a storm scene", conflicted: false }),
    event(6, "proposal.rejected", { summary: "Other" }),
    event(7, "turn.failed", { error_code: "provider_timeout" }),
    event(8, "turn.cancelled", {}),
  ]);
  assert.deepEqual(lines.map(line => [line.label, line.tone]), [
    ["Conversation started", "neutral"],
    ["Request", "neutral"],
    ["Reply", "neutral"],
    ["Changes proposed", "neutral"],
    ["Proposal accepted", "good"],
    ["Proposal rejected", "muted"],
    ["Reply failed", "bad"],
    ["Reply stopped", "muted"],
  ]);
  assert.equal(lines[1].detail, "Add a storm.");
  assert.equal(lines[6].detail, "provider timeout");
});

test("an unusable or conflicted proposal says so", () => {
  const [invalid, conflict] = log.logLines([
    event(1, "proposal.created", { summary: "Broken", status: "invalid" }),
    event(2, "proposal.accepted", { summary: "Late", conflicted: true }),
  ]);
  assert.deepEqual([invalid.label, invalid.tone], ["Proposal couldn't be used", "bad"]);
  assert.deepEqual([conflict.label, conflict.tone], ["Accepted as a conflict copy", "bad"]);
});

test("a long text is shortened, and an event from a newer server still shows", () => {
  const [long, future] = log.logLines([
    event(1, "turn.requested", { request: "x".repeat(900) }),
    event(2, "something.new", { anything: 1 }),
  ]);
  assert.ok(long.detail.length <= 240 && long.detail.endsWith("…"));
  assert.deepEqual([future.label, future.detail, future.tone], ["something new", undefined, "neutral"]);
});
