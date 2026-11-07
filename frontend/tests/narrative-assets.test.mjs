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

const item = (id, job_id, extra = {}) => ({ id, job_id, kind: "sprite", character_id: "kaito", created_at: "2026-11-07T10:00:00Z", ...extra });

test("the options from one Generate stay together, wherever they fall in the list", () => {
  const sets = model.assetSets([item("a", "one"), item("b", "two"), item("c", "one"), item("d", "two")], { kaito: "Kaito" });
  assert.deepEqual(sets.map(set => [set.title, set.options, set.assets.map(asset => asset.id)]), [
    ["Kaito · Sprite", 2, ["a", "c"]],
    ["Kaito · Sprite", 2, ["b", "d"]],
  ]);
  assert.equal(sets[0].created_at, "2026-11-07T10:00:00Z");
  assert.notEqual(sets[0].key, sets[1].key);
});

test("uploads and single results keep their place between the sets", () => {
  const sets = model.assetSets([item("u1", null), item("u2", null), item("a", "one"), item("b", "one"), item("single", "two"), item("u3", null)]);
  assert.deepEqual(sets.map(set => [set.title, set.assets.map(asset => asset.id)]), [
    [null, ["u1", "u2"]],
    ["Sprite", ["a", "b"]],
    [null, ["single", "u3"]],
  ]);
});

test("a set is named by its kind when the person is not known", () => {
  const unknown = model.assetSets([item("a", "one"), item("b", "one")], {});
  assert.equal(unknown[0].title, "Sprite");
  const scenery = model.assetSets([item("a", "one", { kind: "background", character_id: null }), item("b", "one", { kind: "background", character_id: null })], { kaito: "Kaito" });
  assert.equal(scenery[0].title, "Background");
  assert.deepEqual(model.assetSets([]), []);
});

test("filters map to library queries", () => {
  assert.deepEqual(model.filterQuery("all"), {});
  assert.deepEqual(model.filterQuery("background"), { kind: "background" });
  assert.deepEqual(model.filterQuery("candidates"), { status: "candidate" });
  assert.deepEqual(model.FILTERS.map(([id]) => id),
    ["all", "background", "sprite", "image", "font", "character_portrait", "candidates"]);
});

test("CGs have a library section and upload as ordinary image assets", () => {
  assert.deepEqual(model.FILTERS.find(([id]) => id === "image"), ["image", "CGs"]);
  assert.deepEqual(model.filterQuery("image"), { kind: "image" });
  assert.equal(model.uploadKindForFilter("image"), "image");
  assert.equal(model.uploadKindForFilter("background"), "background");
  assert.equal(model.uploadKindForFilter("sprite"), "sprite");
  assert.equal(model.uploadKindForFilter("font"), "font");
  assert.equal(model.uploadKindForFilter("all"), "background");
  assert.equal(model.KIND_LABELS.image, "CG / image");
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
