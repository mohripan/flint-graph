import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/narrative/gpuModel.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } });
const gpu = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
const status = (state, extra = {}) => ({ state, detail: null, wake_seconds: null, waiting: ["image", "voice", "assistant"], ...extra });

test("nothing is said when the work would not wait", () => {
  assert.equal(gpu.gpuMessage(null, ["image"]), null, "no reading, no claim");
  assert.equal(gpu.gpuMessage(status("ready", { waiting: [] }), ["image"]), null);
  assert.equal(gpu.gpuMessage(status("asleep"), ["pose"]), null, "this server does not run that here");
  assert.equal(gpu.gpuMessage(status("asleep", { waiting: ["voice"] }), ["image"]), null);
});

test("asleep says why it is off, how long it takes, and that the request starts by itself", () => {
  const message = gpu.gpuMessage(status("asleep", { wake_seconds: 150 }), ["image"]);
  assert.equal(message.bad, false);
  assert.match(message.title, /nap/);
  assert.match(message.body, /to save money/);
  assert.match(message.body, /about 3 minutes/);
  assert.match(message.body, /starts by itself/);
});

test("a wake-up time is only claimed when one was measured", () => {
  assert.equal(gpu.wakeTime(null), "a few minutes");
  assert.equal(gpu.wakeTime(60), "about a minute");
  assert.equal(gpu.wakeTime(180), "about 3 minutes");
  assert.match(gpu.gpuMessage(status("starting"), ["assistant"]).body, /a few minutes/);
});

test("waking and dozing off read as a wait, not a failure", () => {
  assert.equal(gpu.gpuMessage(status("starting"), ["image"]).bad, false);
  assert.match(gpu.gpuMessage(status("starting"), ["image"]).title, /Waking the GPU/);
  assert.equal(gpu.gpuMessage(status("stopping"), ["image"]).bad, false);
});

test("when it cannot wake, the message says so plainly and keeps the job in line", () => {
  for (const [detail, words] of [["no_capacity", /No GPU is free/], ["daily_cap", /clocked off/], ["controller_down", /won't wake up/], [null, /won't wake up/]]) {
    const message = gpu.gpuMessage(status("unavailable", { detail }), ["image"]);
    assert.equal(message.bad, true, detail);
    assert.match(message.title, words);
    assert.match(message.body, /stays in line/);
    assert.doesNotMatch(message.body, /minutes/, "no wake-up is coming");
  }
});

test("where nothing wakes it, the message never promises a wake-up", () => {
  const one = gpu.gpuMessage(status("off"), ["image"]);
  assert.equal(one.title, "The picture worker isn't running.");
  assert.doesNotMatch(one.body, /wake|nap/);
  assert.equal(gpu.gpuMessage(status("off"), ["image", "voice"]).title, "The picture and voice workers aren't running.");
  assert.equal(gpu.gpuMessage(status("off", { waiting: ["voice"] }), ["image", "voice"]).title, "The voice worker isn't running.");
});

test("an action waits on the worker that runs it", () => {
  assert.equal(gpu.actionGpuKind("generate_backgrounds"), "image");
  assert.equal(gpu.actionGpuKind("generate_voice"), "voice");
  assert.equal(gpu.actionGpuKind("start_child_session"), "assistant");
});
