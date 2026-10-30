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
