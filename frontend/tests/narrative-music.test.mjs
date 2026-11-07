import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function load(name) {
  const source = await readFile(new URL(`../src/narrative/${name}.ts`, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } });
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
}
const music = await load("musicModel");

test("a description has to say something, within the limit", () => {
  assert.ok(music.descriptionProblem("   "));
  assert.equal(music.descriptionProblem("calm piano"), null);
  assert.ok(music.descriptionProblem("x".repeat(501)));
});

test("lengths read like a person wrote them", () => {
  assert.equal(music.lengthLabel(30), "30 seconds");
  assert.equal(music.lengthLabel(60), "1 minute");
  assert.equal(music.lengthLabel(90), "1 minute 30 seconds");
  assert.equal(music.lengthLabel(180), "3 minutes");
  // The server's limits: every choice offered must be accepted.
  assert.ok(music.TRACK_LENGTHS.every(seconds => seconds >= 15 && seconds <= 180));
  assert.ok(music.TRACK_LENGTHS.includes(music.DEFAULT_LENGTH));
});

test("every state of a job says what is happening", () => {
  const job = status => ({ status, error_code: null, cancel_requested: false });
  assert.match(music.musicJobText(job("queued")), /Waiting/);
  assert.match(music.musicJobText(job("running")), /Composing/);
  assert.match(music.musicJobText({ ...job("running"), cancel_requested: true }), /Stopping/);
  assert.match(music.musicJobText(job("completed")), /approve/);
  assert.match(music.musicJobText({ ...job("failed"), error_code: "gpu_busy" }), /busy/);
  assert.match(music.musicJobText({ ...job("failed"), error_code: "an_unknown_code" }), /Try again/);
  assert.equal(music.musicJobActive(job("running")), true);
  assert.equal(music.musicJobActive(job("completed")), false);
});
