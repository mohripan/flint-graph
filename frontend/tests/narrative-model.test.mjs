import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/narrative/model.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext },
});
const model = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

test("script summaries name CG-only steps and explicit clears", () => {
  assert.equal(model.describeStage(originalStory(), { type: "stage", cg: "train", next: "finish" }), "CG train");
  assert.equal(model.describeStage(originalStory(), { type: "stage", cg: null, next: "finish" }), "Clear CG");
});

function originalStory() {
  return {
    schema_version: "1", id: "original", title: "An original mystery", language: "en",
    entry: "start", characters: {}, variables: {}, assets: {},
    nodes: {
      start: { type: "line", text_id: "start_text", text: "The lantern waits.", next: "finish" },
      finish: { type: "end", text_id: "finish_text", text: "Dawn.", ending: "complete" },
    },
  };
}

test("an author can add a choice without changing the loaded revision", () => {
  const loaded = originalStory();
  const before = structuredClone(loaded);
  const added = model.addScene(loaded, "choice");

  assert.deepEqual(loaded, before);
  assert.equal(added.story.nodes[added.id].type, "choice");
  assert.equal(added.story.nodes[added.id].options.length, 2);
  assert.deepEqual(added.story.nodes[added.id].options.map(option => option.target), ["finish", "finish"]);
  const textIds = [added.story.nodes[added.id].text_id,
    ...added.story.nodes[added.id].options.map(option => option.text_id)];
  assert.equal(new Set(textIds).size, 3);
  assert.equal(added.story.entry, "start");
});

test("valid scene IDs such as constructor resolve only as own map keys", () => {
  const story = originalStory();
  assert.equal(model.getScene(story, "constructor"), undefined);
  story.nodes.constructor = { type: "line", text_id: "constructor_text",
    text: "Original constructor scene.", next: "finish" };
  story.nodes.prototype = { type: "line", text_id: "prototype_text",
    text: "Original prototype scene.", next: "finish" };
  assert.equal(model.getScene(story, "constructor").text, "Original constructor scene.");
  assert.equal(model.getScene(story, "prototype").text, "Original prototype scene.");
  const added = model.addScene(story, "choice");
  assert.equal(model.getScene(added.story, "constructor").text, "Original constructor scene.");
});

test("an author can introduce typed state and condition nodes without string coercion", () => {
  const original = originalStory();
  const variable = model.addVariable(original, "int");
  assert.equal(variable.story.variables[variable.id].initial, 0);
  assert.deepEqual(original.variables, {});
  const state = model.addScene(variable.story, "set");
  assert.deepEqual(state.story.nodes[state.id].operations, [
    { op: "set", variable: variable.id, value: 0 },
  ]);
  const branch = model.addScene(state.story, "branch");
  assert.deepEqual(branch.story.nodes[branch.id].condition,
    { op: "eq", variable: variable.id, value: 0 });
  assert.deepEqual(model.sceneTargets(branch.story.nodes[branch.id]), ["finish", "finish"]);
  assert.throws(() => model.addScene(original, "branch"), /variable/i);
  const flag = model.addVariable(original, "bool");
  assert.equal(flag.story.variables[flag.id].initial, false);
});

test("deleting a referenced scene preserves the story until routes are rewired", () => {
  const story = originalStory();
  assert.throws(() => model.deleteScene(story, "finish"), /referenced/i);
  assert.equal(story.nodes.start.next, "finish");
  assert.throws(() => model.deleteScene(story, "start"), /entry/i);
  const added = model.addScene(story, "line");
  const removed = model.deleteScene(added.story, added.id);
  assert.equal(model.getScene(removed, added.id), undefined);
  assert.ok(model.getScene(added.story, added.id));
});

test("an author can extend a choice and introduce an original character", () => {
  const choice = model.addScene(originalStory(), "choice");
  const extended = model.addChoiceOption(choice.story, choice.id);
  assert.equal(extended.nodes[choice.id].options.length, 3);
  assert.equal(choice.story.nodes[choice.id].options.length, 2);
  assert.equal(new Set(extended.nodes[choice.id].options.map(option => option.id)).size, 3);
  const character = model.addCharacter(extended);
  assert.equal(character.story.characters[character.id].name, "New character");
  assert.deepEqual(extended.characters, {});
});

test("condition editing keeps the portable depth and total-check limits", () => {
  const leaf = { op: "eq", variable: "flag", value: true };
  let condition = leaf;
  for (let i = 0; i < 7; i += 1) condition = { op: "not", child: condition };
  assert.strictEqual(model.checkCondition(condition), condition);
  assert.throws(() => model.checkCondition({ op: "not", child: condition }), /eight|8/i);
  assert.throws(() => model.checkCondition({ op: "all", children: Array(64).fill(leaf) }), /64/i);
});

test("character and state removal never silently breaks dialogue or conditions", () => {
  const character = model.addCharacter(originalStory());
  character.story.nodes.start.speaker = character.id;
  assert.throws(() => model.deleteCharacter(character.story, character.id), /referenced|speaker/i);
  const variable = model.addVariable(originalStory(), "bool");
  const branch = model.addScene(variable.story, "branch");
  assert.throws(() => model.deleteVariable(branch.story, variable.id), /referenced|condition/i);
  const removed = model.deleteVariable(variable.story, variable.id);
  assert.deepEqual(removed.variables, {});
  assert.ok(variable.story.variables[variable.id]);
});
