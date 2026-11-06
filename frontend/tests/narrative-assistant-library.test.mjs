import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/narrative/assistantLibrary.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
const library = await import(`data:text/javascript;base64,${Buffer.from(outputText + "\n//# sourceURL=assistant-library.js").toString("base64")}`);

const story = { characters: { mira: { name: "Mira" }, ren: { name: "Ren Akagi" } } };
const asset = (id, kind, name, extra = {}) => ({ id, kind, name, media_type: kind === "voice" ? "audio/wav" : "image/png", character_id: null, ...extra });
const assets = [
  asset("a1", "background", "Rainy street"),
  asset("a2", "sprite", "Mira smile", { character_id: "mira" }),
  asset("a3", "image", "Bell CG"),
  asset("a4", "character_portrait", "Ren portrait", { character_id: "ren" }),
  asset("a5", "voice", "I can hear the bell"),
  asset("a6", "font", "Serif", { media_type: "font/ttf" }),
];

test("each tab offers its own kind, and fonts stay out", () => {
  assert.deepEqual(library.libraryChoices(story, assets, "characters", "").map(item => item.id), ["mira", "ren"]);
  assert.deepEqual(library.libraryChoices(story, assets, "pictures", "").map(item => item.id), ["a1", "a2", "a3", "a4"]);
  assert.deepEqual(library.libraryChoices(story, assets, "voices", "").map(item => item.id), ["a5"]);
});

test("a choice carries what the chip and the server need", () => {
  assert.deepEqual(library.libraryChoices(story, assets, "characters", "")[1],
    { kind: "character", id: "ren", name: "Ren Akagi", asset_kind: null });
  assert.deepEqual(library.libraryChoices(story, assets, "pictures", "")[0],
    { kind: "asset", id: "a1", name: "Rainy street", asset_kind: "background" });
});

test("search matches any part of the name, ignoring case", () => {
  assert.deepEqual(library.libraryChoices(story, assets, "characters", "AKAG").map(item => item.id), ["ren"]);
  assert.deepEqual(library.libraryChoices(story, assets, "pictures", "  street ").map(item => item.id), ["a1"]);
  assert.deepEqual(library.libraryChoices(story, assets, "pictures", "nothing"), []);
});

test("searching finds a character's pictures by their name too", () => {
  assert.deepEqual(library.libraryChoices(story, assets, "pictures", "ren").map(item => item.id), ["a4"]);
});

test("no story or no assets simply offers nothing", () => {
  assert.deepEqual(library.libraryChoices(null, null, "characters", ""), []);
  assert.deepEqual(library.libraryChoices(story, null, "pictures", ""), []);
});

test("choosing toggles an attachment, up to the limit", () => {
  const mira = { kind: "character", id: "mira", name: "Mira", asset_kind: null };
  const street = { kind: "asset", id: "a1", name: "Rainy street", asset_kind: "background" };
  let attached = library.toggleAttachment([], mira);
  attached = library.toggleAttachment(attached, street);
  assert.deepEqual(attached.map(item => item.id), ["mira", "a1"]);
  assert.equal(library.isAttached(attached, street), true);
  attached = library.toggleAttachment(attached, mira);
  assert.deepEqual(attached.map(item => item.id), ["a1"]);
  assert.equal(library.isAttached(attached, mira), false);
  const full = Array.from({ length: library.MAX_ATTACHMENTS }, (_, index) => ({ ...street, id: `x${index}` }));
  assert.equal(library.toggleAttachment(full, street), full, "over the limit changes nothing");
});

test("a chip says what kind of thing it is", () => {
  assert.equal(library.attachmentKind({ kind: "character", asset_kind: null }), "Character");
  assert.equal(library.attachmentKind({ kind: "asset", asset_kind: "background" }), "Background");
  assert.equal(library.attachmentKind({ kind: "asset", asset_kind: "sprite" }), "Sprite");
  assert.equal(library.attachmentKind({ kind: "asset", asset_kind: "voice" }), "Voice");
  assert.equal(library.attachmentKind({ kind: "asset", asset_kind: "image" }), "Picture");
  assert.equal(library.attachmentKind({ kind: "asset", asset_kind: "character_portrait" }), "Portrait");
});
