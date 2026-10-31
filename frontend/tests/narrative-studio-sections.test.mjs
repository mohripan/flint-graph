import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
const source = await readFile(new URL("../src/narrative/studioSections.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } });
const sections = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

test("the sidebar lists every Studio panel once, leaving Scenes to the Write rail", () => {
  const listed = sections.SECTION_GROUPS.flatMap(group => group.panels);
  assert.deepEqual([...listed].sort(), sections.PANELS.map(([id]) => id).filter(id => id !== "scenes").sort());
  assert.equal(new Set(listed).size, listed.length);
  assert.deepEqual(sections.SECTION_GROUPS.map(group => group.label), ["Writing", "Cast & art", "Story setup", "Advanced"]);
  assert.equal(sections.panelLabel("story"), "Details");
});

test("the current entry follows the open view", () => {
  assert.equal(sections.currentSection(true, "assets"), "assistant");
  assert.equal(sections.currentSection(false, "scenes"), "write");
  assert.equal(sections.currentSection(false, "look"), "look");
});
