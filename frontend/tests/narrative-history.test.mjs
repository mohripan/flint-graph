import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
const source = await readFile(new URL("../src/narrative/history.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } });
const { DraftHistory } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

test("undo/redo preserves exact draft strings and new work replaces the redo branch", () => {
  const history = new DraftHistory();
  history.record("first");
  history.record("second");
  assert.equal(history.undo("third"), "second");
  assert.equal(history.redo("second"), "third");
  assert.equal(history.undo("third"), "second");
  history.record("second");
  assert.equal(history.redo("changed"), null);
  history.clear();
  assert.equal(history.undo("anything"), null);
});

test("history bounds retained UTF-8 bytes and coalesces a field's continuous typing", () => {
  const history = new DraftHistory(8, 10);
  history.record("🌌🌌"); // Eight bytes, not four UTF-16 code units.
  history.record("a");
  assert.equal(history.undo("b"), "a");
  assert.equal(history.undo("a"), null);
  const typing = new DraftHistory();
  typing.record("before", "scene-text");
  typing.record("t", "scene-text");
  typing.record("ty", "scene-text");
  assert.equal(typing.undo("typing"), "before");
});
