import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function load(name) {
  const text = await readFile(new URL(`../src/narrative/${name}.ts`, import.meta.url), "utf8");
  const code = ts.transpileModule(text, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);
}
const delivery = await load("voiceDelivery");
const stage = await load("stageModel");
const terms = JSON.parse(await readFile(new URL("../../tests/fixtures/narrative/player_terms.json", import.meta.url), "utf8"));
const expand = text => text.replaceAll("{notices}", terms.markers.notices).replaceAll("{begin}", terms.markers.begin)
  .replaceAll("{end}", terms.markers.end);

test("player terms follow the shared contract every runtime runs", () => {
  assert.deepEqual(terms.markers, { notices: stage.NOTICE_MARKER, begin: stage.TERMS_BEGIN, end: stage.TERMS_END });
  for (const item of terms.cases) {
    const notices = expand(item.notices);
    if (item.error) assert.throws(() => stage.playerTerms(notices), new RegExp(item.error), item.name);
    else assert.equal(stage.playerTerms(notices), item.terms, item.name);
  }
});

test("a line's delivery defaults from its expression and an override wins", () => {
  assert.deepEqual(delivery.lineDelivery(undefined, "crying"),
    { delivery: { emotion: "sad", intensity: 0.9, tag: null }, source: "expression" });
  assert.deepEqual(delivery.lineDelivery(undefined, "Laughing ").delivery.emotion, "happy");
  assert.equal(delivery.lineDelivery(undefined, "thinking").source, "default");
  assert.equal(delivery.lineDelivery(undefined, undefined).delivery, delivery.NEUTRAL);
  const chosen = { emotion: "whisper", intensity: 0.2, tag: null };
  assert.deepEqual(delivery.lineDelivery(chosen, "angry"), { delivery: chosen, source: "override" });
  assert.equal(delivery.DELIVERIES.length, 10);
});

test("a voice shows which deliveries it cannot do instead of ignoring them", () => {
  const kokoro = { name: "Kokoro-82M", deliveries: { neutral: "full" }, tags: [] };
  const turbo = { name: "Chatterbox-Turbo", deliveries: { neutral: "full", angry: "approximate" }, tags: ["laugh"] };
  const whisper = delivery.spokenDelivery(kokoro, { emotion: "whisper", intensity: 0.5, tag: null });
  assert.deepEqual(whisper.delivery, { emotion: "neutral", intensity: 0.5, tag: null });
  assert.match(whisper.note, /Kokoro-82M cannot speak a line whisper; this clip will sound neutral/);
  const laugh = delivery.spokenDelivery(turbo, { emotion: "angry", intensity: 0.8, tag: "laugh" });
  assert.deepEqual(laugh.delivery, { emotion: "angry", intensity: 0.8, tag: "laugh" });
  assert.match(laugh.note, /only approximates angry/);
  const sigh = delivery.spokenDelivery(kokoro, { emotion: "neutral", intensity: 0.5, tag: "sigh" });
  assert.equal(sigh.delivery.tag, null);
  assert.match(sigh.note, /make the sound “sigh”/);
  assert.equal(delivery.spokenDelivery(kokoro, delivery.NEUTRAL).note, null);
});
