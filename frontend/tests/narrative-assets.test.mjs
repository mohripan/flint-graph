import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function load(name) {
  const source = await readFile(new URL(`../src/narrative/${name}.ts`, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
  return import(`data:text/javascript;base64,${Buffer.from(outputText + `\n//# sourceURL=${name}.js`).toString("base64")}`);
}
const model = await load("assetModel");

test("filters map to library queries", () => {
  assert.deepEqual(model.filterQuery("all"), {});
  assert.deepEqual(model.filterQuery("background"), { kind: "background" });
  assert.deepEqual(model.filterQuery("candidates"), { status: "candidate" });
  assert.deepEqual(model.FILTERS.map(([id]) => id),
    ["all", "background", "sprite", "image", "font", "character_portrait", "candidates"]);
});

test("uploads are checked before sending", () => {
  const file = (name, size) => ({ name, size });
  assert.equal(model.uploadProblem(file("bg.png", 1000), "background"), null);
  assert.equal(model.uploadProblem(file("Old Type.TTF", 1000), "font"), null);
  assert.equal(model.uploadProblem(file("type.otf", 1000), "font"), null);
  assert.match(model.uploadProblem(file("bg.jpg", 1000), "background"), /PNG/);
  assert.match(model.uploadProblem(file("type.woff2", 1000), "font"), /TTF or OTF/);
  assert.match(model.uploadProblem(file("big.png", 11 * 1024 * 1024), "image"), /10 MB/);
  assert.match(model.uploadProblem(file("big.ttf", 9 * 1024 * 1024), "font"), /8 MB/);
  assert.equal(model.suggestName("harbor_dusk-final.png"), "harbor dusk final");
  assert.equal(model.kindForFile("sprite.png"), "image");
  assert.equal(model.kindForFile("Lora.ttf"), "font");
});

test("font families are unique and safe per asset", () => {
  assert.equal(model.fontFamily("7b8c-aa"), "flint-asset-7b8c-aa");
});
