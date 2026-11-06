import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/narrative/assistantThreads.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
const model = await import(`data:text/javascript;base64,${Buffer.from(outputText + "\n//# sourceURL=assistant-threads.js").toString("base64")}`);

const thread = (id, extra = {}) => ({ id, title: id, parent_thread_id: null, children: [], active: false, created_at: "2026-11-06", ...extra });
const child = (id, parent, extra = {}) => thread(id, { parent_thread_id: parent, ...extra });

test("a thread can be found wherever it sits in the tree", () => {
  const roots = [thread("a", { children: [child("a1", "a")] }), thread("b")];
  assert.equal(model.findThread(roots, "a1").id, "a1");
  assert.equal(model.findThread(roots, "b").id, "b");
  assert.equal(model.findThread(roots, "missing"), undefined);
  assert.equal(model.findThread(roots, null), undefined);
});

test("a parent shows open while its child is the open conversation, whatever was toggled", () => {
  const roots = [thread("a", { children: [child("a1", "a")] }), thread("b", { children: [child("b1", "b")] })];
  assert.deepEqual(model.visibleThreads(roots, new Set(), "a1").map(row => row.id), ["a", "a1", "b"]);
  assert.deepEqual(model.visibleThreads(roots, new Set(["b"]), "a").map(row => row.id), ["a", "a1", "b", "b1"],
    "opening a parent shows its children");
  assert.deepEqual(model.visibleThreads(roots, new Set(), null).map(row => row.id), ["a", "b"]);
});

test("a child that is working opens its parent so the spinner can be seen", () => {
  const roots = [thread("a", { children: [child("a1", "a", { active: true })] })];
  assert.deepEqual(model.visibleThreads(roots, new Set(), null).map(row => row.id), ["a", "a1"]);
});

test("each row knows its depth and whether it ends its group, for the connector line", () => {
  const roots = [thread("a", { children: [child("a1", "a"), child("a2", "a")] }), thread("b")];
  const rows = model.visibleThreads(roots, new Set(["a"]), null);
  assert.deepEqual(rows.map(row => [row.id, row.depth, row.last]), [
    ["a", 0, false], ["a1", 1, false], ["a2", 1, true], ["b", 0, false],
  ]);
});

test("a parent says how many children it has and if any are working", () => {
  const roots = [thread("a", { children: [child("a1", "a", { active: true }), child("a2", "a")] }), thread("b")];
  const [a, , , b] = model.visibleThreads(roots, new Set(["a"]), null);
  assert.deepEqual([a.childCount, a.busy], [2, true]);
  assert.deepEqual([b.childCount, b.busy], [0, false]);
});

test("a refreshed list replaces the old one without losing a thread only this page knows", () => {
  const known = [thread("new"), thread("a")];
  const merged = model.mergeThreads(known, [thread("a", { title: "fresh" })], { keepIds: new Set(["new"]) });
  assert.deepEqual(merged.map(row => [row.id, row.title]), [["new", "new"], ["a", "fresh"]]);
});

test("older pages add to the list instead of replacing it", () => {
  const merged = model.appendThreads([thread("a")], [thread("a"), thread("b")]);
  assert.deepEqual(merged.map(row => row.id), ["a", "b"]);
});

test("a child seen before its parent's list updates is placed under that parent", () => {
  const placed = model.placeThread([thread("a")], child("a1", "a"));
  assert.deepEqual(placed[0].children.map(row => row.id), ["a1"]);
  assert.deepEqual(model.placeThread(placed, child("a1", "a"))[0].children.map(row => row.id), ["a1"], "no duplicate");
});

test("a new root goes first", () => {
  assert.deepEqual(model.placeThread([thread("a")], thread("b")).map(row => row.id), ["b", "a"]);
});
