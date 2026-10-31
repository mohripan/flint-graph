import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function load(name) {
  const source = await readFile(new URL(`../src/narrative/${name}.ts`, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
  return import(`data:text/javascript;base64,${Buffer.from(outputText + `\n//# sourceURL=${name}.js`).toString("base64")}`);
}
const model = await load("characterModel");

const job = (changes = {}) => ({ status: "running", progress: 0, count: 4, cancel_requested: false, error_code: null, assets: [], ...changes });

test("job status reads naturally from queue to completion", () => {
  assert.equal(model.jobStatus(job({ status: "queued" })), "Waiting for the image worker…");
  assert.equal(model.jobStatus(job()), "Loading the model…");
  assert.equal(model.jobStatus(job({ progress: 2 })), "Generated 2 of 4…");
  assert.equal(model.jobStatus(job({ cancel_requested: true })), "Cancelling…");
  assert.equal(model.jobStatus(job({ status: "completed", assets: [{}, {}, {}] })), "3 portraits ready");
  assert.equal(model.jobStatus(job({ status: "completed", assets: [{}] })), "1 portrait ready");
  assert.ok(model.isActive(job()) && model.isActive(job({ status: "queued" })));
  assert.ok(!model.isActive(job({ status: "failed" })) && !model.isActive(null));
});

test("failures explain what to do without exposing internals", () => {
  assert.match(model.jobStatus(job({ status: "failed", error_code: "gpu_busy" })), /GPU is busy/);
  assert.equal(model.jobError("something_new"), "Generation failed. Try again.");
  assert.equal(model.jobError(null), "Generation failed. Try again.");
  assert.equal(model.cleanAppearance("  silver\n hair,   amber eyes "), "silver hair, amber eyes");
  assert.deepEqual(model.CHARACTER_TYPES.map(([id]) => id), ["girl", "boy", "woman", "man", "other"]);
});

test("transparent sprites are a full-body option that reads as sprites", () => {
  assert.ok(model.canCutOut("full_body") && !model.canCutOut("portrait"));
  assert.equal(model.generateLabel(false), "Generate 4 portraits");
  assert.equal(model.generateLabel(true), "Generate 4 sprites");
  assert.equal(model.jobStatus(job({ status: "completed", transparent: true, assets: [{}, {}] })), "2 sprites ready");
  assert.equal(model.jobStatus(job({ status: "completed", transparent: true, assets: [{}] })), "1 sprite ready");
  assert.equal(model.jobStatus(job({ transparent: true, progress: 1 })), "Generated 1 of 4…");
  assert.match(model.jobError("cutout_failed"), /could not be separated/);
  assert.match(model.jobError("cutout_unavailable"), /cutout model/);
});

test("high resolution is on by default for sprites and the details show the final size", () => {
  assert.equal(model.defaultHires(true), true);
  assert.equal(model.defaultHires(false), false);
  const base = { width: 832, height: 1216, output_width: 832, output_height: 1216, hires: null, transparent: false, assets: [] };
  assert.equal(model.jobSize(base), "832×1216");
  const hires = { ...base, output_width: 1664, output_height: 2432, hires: { scale: 2, strength: 0.35 } };
  assert.equal(model.jobSize(hires), "1664×2432 (rendered at 832×1216, upscaled 2× and refined at strength 0.35)");
  const sprites = { ...hires, transparent: true, assets: [{ width: 1100, height: 2390 }, { width: 980, height: 2400 }, { width: 1100, height: 2390 }] };
  assert.equal(model.jobSize(sprites),
    "1664×2432 (rendered at 832×1216, upscaled 2× and refined at strength 0.35); sprites cropped to 1100×2390, 980×2400");
  assert.equal(model.jobSize({ ...base, transparent: true }), "832×1216");
  assert.match(model.hiresLabel(), /^High resolution: 2× larger/);
});
