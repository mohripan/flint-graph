import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function load(name) {
  const source = await readFile(new URL(`../src/narrative/${name}.ts`, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
  return import(`data:text/javascript;base64,${Buffer.from(outputText + `\n//# sourceURL=${name}.js`).toString("base64")}`);
}
const model = await load("assetFolders");

const folders = [
  { id: "f-night", parent_id: "f-harbor", name: "night", asset_count: 1 },
  { id: "f-cast", parent_id: null, name: "Cast", asset_count: 0 },
  { id: "f-harbor", parent_id: "f-ch1", name: "Harbor", asset_count: 3 },
  { id: "f-ch1", parent_id: null, name: "chapter 1", asset_count: 2 },
];

test("library views map to asset queries", () => {
  assert.deepEqual(model.viewQuery({ type: "all" }), {});
  assert.deepEqual(model.viewQuery({ type: "review" }), { status: "candidate" });
  assert.deepEqual(model.viewQuery({ type: "unfiled" }), { folder: "none" });
  assert.deepEqual(model.viewQuery({ type: "kind", kind: "sprite" }), { kind: "sprite" });
  assert.deepEqual(model.viewQuery({ type: "character", id: "mira" }), { character_id: "mira" });
  assert.deepEqual(model.viewQuery({ type: "folder", id: "f-cast" }), { folder: "f-cast" });
  assert.equal(model.sameView({ type: "kind", kind: "font" }, { type: "kind", kind: "font" }), true);
  assert.equal(model.sameView({ type: "kind", kind: "font" }, { type: "kind", kind: "sprite" }), false);
});

test("folders list as an indented tree in name order", () => {
  assert.deepEqual(model.folderRows(folders).map(row => [row.folder.id, row.depth]),
    [["f-cast", 0], ["f-ch1", 0], ["f-harbor", 1], ["f-night", 2]]);
  assert.equal(model.folderPath(folders, "f-night"), "chapter 1 / Harbor / night");
  assert.equal(model.folderPath(folders, "missing"), "");
  // New folders may go under any folder that is not already at the deepest level.
  assert.deepEqual(model.folderRows(folders).filter(row => model.canHoldFolders(row.depth)).map(row => row.folder.id),
    ["f-cast", "f-ch1", "f-harbor"]);
});

test("the rail groups generated items by kind and character without filing", () => {
  const index = { folders, unfiled: 4, to_review: 2, total: 10,
    kinds: { sprite: 3, background: 2, voice: 4, font: 1 }, characters: { mira: 5, quen: 2 } };
  const names = { quen: "Quen Aldwinia" };
  const groups = model.railGroups(index, names);
  assert.deepEqual(groups.library.map(item => [item.label, item.count]),
    [["All assets", 10], ["To review", 2], ["Unsorted", 4]]);
  assert.deepEqual(groups.kinds.map(item => [item.label, item.count]),
    [["Backgrounds", 2], ["Sprites", 3], ["Fonts", 1], ["Voice clips", 4]]);
  assert.deepEqual(groups.characters.map(item => [item.label, item.count]),
    [["mira", 5], ["Quen Aldwinia", 2]]);
  assert.equal(model.viewTitle({ type: "character", id: "quen" }, index, names), "Quen Aldwinia");
  assert.equal(model.viewTitle({ type: "folder", id: "f-harbor" }, index, names), "chapter 1 / Harbor");
  assert.equal(model.viewTitle({ type: "review" }, index, names), "To review");
});

test("folder names are checked before sending", () => {
  assert.equal(model.folderNameProblem("  Harbor  ", folders, "f-ch1"), "A folder named “Harbor” is already here.");
  assert.equal(model.folderNameProblem("harbor", folders, null), null);
  assert.equal(model.folderNameProblem("   ", folders, null), "Give the folder a name.");
  assert.match(model.folderNameProblem("x".repeat(81), folders, null), /80/);
  assert.equal(model.folderNameProblem("Cast", folders, null, "f-cast"), null, "Renaming to its own name is fine");
});

test("uploads start in the kind the creator is viewing", () => {
  assert.equal(model.uploadKindForView({ type: "kind", kind: "image" }), "image");
  assert.equal(model.uploadKindForView({ type: "kind", kind: "voice" }), "voice");
  assert.equal(model.uploadKindForView({ type: "kind", kind: "character_portrait" }), "background");
  assert.equal(model.uploadKindForView({ type: "folder", id: "f-cast" }), "background");
});
