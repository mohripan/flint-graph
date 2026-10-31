import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function source(name) {
  const text = await readFile(new URL(`../src/narrative/${name}.ts`, import.meta.url), "utf8");
  return ts.transpileModule(text, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } }).outputText;
}
// voiceModel imports stageModel; inline both so the relative import resolves.
const stageCode = await source("stageModel");
const voiceCode = (await source("voiceModel")).replace(/import \{[^}]*\} from "\.\/stageModel";/,
  `const { bindAsset, pruneAssets } = await import("data:text/javascript;base64,${Buffer.from(stageCode).toString("base64")}");`);
const voice = await import(`data:text/javascript;base64,${Buffer.from(voiceCode).toString("base64")}`);
const stage = await import(`data:text/javascript;base64,${Buffer.from(stageCode).toString("base64")}`);
const cases = JSON.parse(await readFile(new URL("../../tests/fixtures/narrative/line_voices.json", import.meta.url), "utf8"));

function variant(item) {
  const story = structuredClone(cases.story);
  Object.assign(story.nodes[item.node], item.set ?? {});
  for (const name of item.drop ?? []) delete story.nodes[item.node][name];
  return story;
}

test("line voices share the player contract and stable codes", () => {
  for (const id of Object.keys(cases.story.nodes)) assert.equal(voice.voiceProblem(cases.story, id), null);
  for (const item of cases.invalid.filter(entry => entry.location.startsWith(`nodes.${entry.node}.voice`))) {
    assert.deepEqual(voice.voiceProblem(variant(item), item.node), { code: item.code, location: item.location }, item.location);
  }
  const screens = cases.screens.map(id => voice.lineClip(cases.story, id));
  assert.deepEqual(screens, cases.voices);
  assert.ok(stage.usedAssets(cases.story).has("fufu") && stage.usedAssets(cases.story).has("hello"));
});

test("choosing silent, full voice or a vocalization edits the same line node", () => {
  let story = structuredClone(cases.story);
  assert.equal(voice.voiceChoice(story.nodes.silent), "silent");
  story = voice.setLineVoice(story, "hello", "silent");
  assert.equal(story.nodes.hello.voice, undefined);
  assert.equal(story.assets.hello, undefined, "an unused clip leaves the story");
  story = voice.setLineVoice(story, "pending", "vocalization", "hmm");
  assert.deepEqual(story.nodes.pending.voice, { mode: "vocalization", text: "hmm" });
  assert.equal(voice.spokenText(story, "pending"), "hmm");
  story = voice.setLineVoice(story, "laugh", "full");
  assert.deepEqual(story.nodes.laugh.voice, { mode: "full" }, "a vocalization clip does not speak the line");
  assert.equal(voice.spokenText(story, "laugh"), "Or someone never left.");
  assert.throws(() => voice.setLineVoice(story, "silent", "full"), /speaks/);
  story = voice.setLineVoice(story, "pending", "vocalization", "  ufufu  ");
  assert.equal(story.nodes.pending.voice.text, "ufufu");
  assert.throws(() => voice.setLineVoice(story, "pending", "vocalization", "x".repeat(41)), /40/);

  const clip = { sha256: "e".repeat(64), media_type: "audio/wav", name: "Mira hmm" };
  story = voice.setLineClip(story, "pending", clip);
  assert.equal(story.nodes.pending.voice.audio, "mira_hmm");
  assert.deepEqual(story.assets.mira_hmm, { kind: "audio", path: "assets/mira_hmm.wav", sha256: "e".repeat(64) });
  story = voice.setLineClip(story, "pending", null);
  assert.equal(story.nodes.pending.voice.audio, undefined);
  assert.equal(story.assets.mira_hmm, undefined);
});

test("speakers own their voices", () => {
  let story = structuredClone(cases.story);
  story = voice.withSpeaker(stage.setLineSpeaker(story, "hello", "quen"), cases.story, "hello");
  assert.deepEqual(story.nodes.hello.voice, { mode: "full" }, "another character's clip is dropped");
  story = voice.withSpeaker(stage.setLineSpeaker(story, "hello", null), cases.story, "hello");
  assert.equal(story.nodes.hello.voice, undefined, "narration is silent");
});

test("missing clips are grouped by speaker for one job each and stale clips are noticed", () => {
  const story = structuredClone(cases.story);
  story.nodes.silent.speaker = "quen";
  story.nodes.silent.voice = { mode: "vocalization", text: "ah" };
  assert.deepEqual(voice.missingClips(story, ["hello", "laugh", "pending", "silent"]), {
    mira: [{ mode: "full", text: "Not voiced yet.", node_id: "pending" }],
    quen: [{ mode: "vocalization", text: "ah", node_id: "silent" }],
  });
  const made = { provenance: { mode: "full", text: "The lanterns are lit again." } };
  assert.equal(voice.clipIsStale(story, "hello", made), false);
  story.nodes.hello.text = "The lanterns are lit.";
  assert.equal(voice.clipIsStale(story, "hello", made), true);
  assert.equal(voice.clipIsStale(story, "hello", { provenance: { source: "upload" } }), false);
});
