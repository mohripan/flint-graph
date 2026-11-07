import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function load(name) {
  const source = await readFile(new URL(`../src/narrative/${name}.ts`, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } });
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
}
const passages = await load("passages");

const story = () => ({
  schema_version: "2", id: "s", title: "S", language: "en", entry: "open", characters: {}, variables: {}, assets: {},
  nodes: {
    open: { type: "line", text_id: "open", text: "Hello.", next: "ask" },
    ask: { type: "name", text_id: "ask", text: "Your name?", next: "after" },
    after: { type: "line", text_id: "after", text: "Hi, {name}.", next: "end" },
    end: { type: "end", text_id: "end", text: "Bye.", ending: "done" },
  },
});

test("asking for a name closes a scene and the story carries on after it", () => {
  const { passages: rows, owner } = passages.buildPassages(story());
  assert.deepEqual(rows.find(row => row.id === "open").nodes, ["open", "ask"], "the scene leads into the question");
  assert.equal(rows.find(row => row.id === "open").exit, "ask");
  assert.equal(owner.get("after"), "after", "what follows is its own scene");
  assert.ok(rows.some(row => row.id === "after"));
});

test("a question on its own reads as what it is", () => {
  const alone = story();
  alone.entry = "ask";
  delete alone.nodes.open;
  const row = passages.buildPassages(alone).passages.find(item => item.id === "ask");
  assert.equal(row.kind, "name");
  assert.equal(row.title, "Your name?");
});
