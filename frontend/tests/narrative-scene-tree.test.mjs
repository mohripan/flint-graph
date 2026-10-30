import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function load(name) {
  const source = await readFile(new URL(`../src/narrative/${name}.ts`, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
  return import(`data:text/javascript;base64,${Buffer.from(outputText + `\n//# sourceURL=${name}.js`).toString("base64")}`);
}
const passages = await load("passages");
const tree = await load("sceneTree");
const model = await load("model");

const line = (text, next, speaker) => ({ type: "line", text_id: `${next}_${text.length}`, text, next, ...(speaker ? { speaker } : {}) });
function story() {
  return {
    schema_version: "1", id: "bell", title: "Bell", language: "en", entry: "opening",
    characters: { oren: { name: "Oren" } }, variables: { courage: { type: "int", initial: 0 } }, assets: {},
    nodes: {
      opening: line("Fog.", "opening_2", "oren"),
      opening_2: line("The bell is silent.", "brave"),
      brave: { type: "set", operations: [{ op: "increment", variable: "courage", value: 1 }], next: "opening_3" },
      opening_3: line("Someone must ring it.", "first_choice"),
      first_choice: { type: "choice", text_id: "fc", text: "What now?", options: [
        { id: "climb", text_id: "c", text: "Climb.", target: "tower" },
        { id: "wait", text_id: "w", text: "Wait.", target: "lost_end" },
      ] },
      tower: line("The stairs creak.", "check"),
      check: { type: "branch", condition: { op: "ge", variable: "courage", value: 1 }, if_true: "rung_end", if_false: "lost_end" },
      rung_end: { type: "end", text_id: "r", text: "It rings.", ending: "rung" },
      lost_end: { type: "end", text_id: "l", text: "Silence.", ending: "lost" },
      orphan_a: line("Loop A.", "orphan_b"),
      orphan_b: line("Loop B.", "orphan_a"),
    },
  };
}

test("lines, state changes and their closing choice form one scene; every node has one owner", () => {
  const { passages: rows, owner } = passages.buildPassages(story());
  assert.deepEqual(rows.map(row => [row.id, row.nodes, row.exit, row.kind]), [
    ["opening", ["opening", "opening_2", "brave", "opening_3", "first_choice"], "first_choice", "scene"],
    ["tower", ["tower", "check"], "check", "scene"],
    ["rung_end", ["rung_end"], "rung_end", "end"],
    ["lost_end", ["lost_end"], "lost_end", "end"],
    ["orphan_a", ["orphan_a", "orphan_b"], null, "scene"],
  ]);
  assert.equal(rows[0].title, "Fog.");
  assert.equal(rows[0].lines, 3);
  assert.equal(owner.get("brave"), "opening");
  assert.equal(new Set(owner.keys()).size, Object.keys(story().nodes).length);
});

test("a shared choice is its own scene and a merge point starts a new one", () => {
  const value = story();
  value.nodes.tower.next = "first_choice";
  const ids = passages.buildPassages(value).passages.map(row => row.id);
  assert.ok(ids.includes("first_choice"), "Two incoming routes make the choice a scene of its own");
  assert.deepEqual(passages.buildPassages(value).passages.find(row => row.id === "opening").nodes,
    ["opening", "opening_2", "brave", "opening_3"]);
});

const g = (id, name, ...items) => ({ type: "group", id, name, collapsed: false, items });
const s = id => ({ type: "scene", id });

test("normalizing drops stale scenes, keeps folders and places new scenes beside their anchor", () => {
  const saved = [g("act_one", "Act one", s("opening"), s("gone")), s("tower")];
  const result = tree.normalizeLayout(saved, ["opening", "tower", "rung_end", "new_scene"], new Map([["new_scene", "opening"]]));
  assert.deepEqual(result, [g("act_one", "Act one", s("opening"), s("new_scene")), s("tower"), s("rung_end")]);
});

test("flattened rows respect collapsed folders, depth and search", () => {
  const items = [g("act", "Act one", s("opening"), g("inner", "Inner", s("tower"))), s("rung_end")];
  assert.deepEqual(tree.flattenTree(items).map(row => [row.key, row.depth]),
    [["group:act", 0], ["scene:opening", 1], ["group:inner", 1], ["scene:tower", 2], ["scene:rung_end", 0]]);
  const collapsed = tree.toggleGroup(items, "act");
  assert.deepEqual(tree.flattenTree(collapsed).map(row => row.key), ["group:act", "scene:rung_end"]);
  const titles = new Map([["opening", "Fog."], ["tower", "The stairs creak."], ["rung_end", "It rings."]]);
  assert.deepEqual(tree.flattenTree(collapsed, { query: "stairs", titles }).map(row => row.key),
    ["group:act", "group:inner", "scene:tower"], "Search reveals matches inside collapsed folders");
});

test("moves reorder, nest and refuse cycles or excessive depth", () => {
  const items = [g("act", "Act one", s("opening"), s("tower")), g("end", "Endings", s("rung_end")), s("lost_end")];
  const reordered = tree.moveItem(items, [0, 1], { parent: [0], index: 0 });
  assert.deepEqual(reordered[0].items.map(item => item.id), ["tower", "opening"]);
  const across = tree.moveItem(items, [2], { parent: [1], index: 1 });
  assert.deepEqual(across.map(item => item.id), ["act", "end"]);
  assert.deepEqual(across[1].items.map(item => item.id), ["rung_end", "lost_end"]);
  const folder = tree.moveItem(items, [1], { parent: [], index: 0 });
  assert.deepEqual(folder.map(item => item.id), ["end", "act", "lost_end"]);
  assert.equal(tree.moveItem(items, [0], { parent: [0], index: 0 }), items, "A folder cannot move into itself");
  let deep = [s("x")];
  for (let level = 0; level < 4; level += 1) deep = [g(`level_${level}`, "L", ...deep)];
  const extra = [...deep, g("outer", "Outer")];
  assert.equal(tree.moveItem(extra, [0], { parent: [1], index: 0 }), extra, "Five levels would exceed the limit");
  assert.equal(tree.canDrop(items, [0], [0, 0]), false);
  assert.equal(tree.canDrop(items, [2], [1]), true);
});

test("folders can be added, renamed and removed without losing scenes", () => {
  let items = [s("opening"), s("tower")];
  items = tree.addGroup(items, { id: "chapter_1", name: "Chapter 1" });
  assert.deepEqual(items.map(item => item.id), ["chapter_1", "opening", "tower"]);
  items = tree.moveItem(items, [1], { parent: [0], index: 0 });
  items = tree.renameGroup(items, "chapter_1", "  Prologue  ");
  assert.equal(items[0].name, "Prologue");
  assert.deepEqual(tree.removeGroup(items, "chapter_1").map(item => item.id), ["opening", "tower"]);
  assert.equal(tree.renameGroup(items, "chapter_1", "   ")[0].name, "Prologue", "Blank names are ignored");
  assert.match(tree.newGroupId(items), /^folder_[a-z0-9]+$/);
});

test("lines can be inserted and removed inside a scene without breaking routes", () => {
  const inserted = model.insertLineAfter(story(), "opening");
  assert.equal(inserted.story.nodes.opening.next, inserted.id);
  assert.equal(inserted.story.nodes[inserted.id].next, "opening_2");
  assert.equal(inserted.story.nodes[inserted.id].speaker, "oren", "A new line keeps the current speaker");
  const removed = model.removeLine(story(), "opening_2");
  assert.equal(removed.nodes.opening.next, "brave");
  assert.equal(removed.nodes.opening_2, undefined);
  const head = model.removeLine(story(), "opening");
  assert.equal(head.entry, "opening_2", "Removing the first line moves the start");
  assert.throws(() => model.removeLine(story(), "first_choice"), /Only lines and state changes/);
});
