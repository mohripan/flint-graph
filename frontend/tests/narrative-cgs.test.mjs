import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function load(name) {
  const source = await readFile(new URL(`../src/narrative/${name}.ts`, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
  return import(`data:text/javascript;base64,${Buffer.from(outputText + `\n//# sourceURL=${name}.js`).toString("base64")}`);
}
const cg = await load("cgModel");
const characters = await load("characterModel");

const asset = (id, kind, changes = {}) => ({
  id, kind, status: "approved", media_type: "image/png", provenance: {}, character_id: "quen", ...changes,
});

test("references are approved images of the character, its chosen portrait first", () => {
  const assets = [
    asset("sprite-new", "sprite"),
    asset("cg", "image", { provenance: { ip_adapter: { scale: 0.5 } } }),
    asset("portrait-other", "character_portrait"),
    asset("candidate", "sprite", { status: "candidate" }),
    asset("background", "background"),
    asset("voice", "voice", { media_type: "audio/wav" }),
    asset("upload", "image"),
    asset("chosen", "character_portrait"),
    asset("sprite-new", "sprite"),
  ];
  const choices = cg.referenceChoices(assets, "chosen").map(item => item.id);
  // Generated CGs carry a whole scene and never stand for the character.
  assert.deepEqual(choices, ["chosen", "portrait-other", "sprite-new", "upload"]);
  assert.deepEqual(cg.referenceChoices(assets, null).map(item => item.id).slice(0, 2), ["portrait-other", "chosen"]);
});

test("the reference stays the creator's pick while it is still offered", () => {
  const choices = [asset("a", "character_portrait"), asset("b", "sprite")];
  assert.equal(cg.defaultReference(choices, null), "a");
  assert.equal(cg.defaultReference(choices, "b"), "b");
  assert.equal(cg.defaultReference(choices, "gone"), "a");
  assert.equal(cg.defaultReference([], "b"), null);
});

test("a CG request needs a character, an approved reference and a bounded scene", () => {
  const ready = { picks: [{ character: "quen", reference: "a" }], scene: "  Quen sitting on the couch\n at night " };
  assert.equal(cg.cgProblem(ready), null);
  assert.match(cg.cgProblem({ ...ready, picks: [{ character: "", reference: "a" }] }), /character/);
  assert.match(cg.cgProblem({ ...ready, picks: [{ character: "quen", reference: null }] }), /Approve/);
  assert.match(cg.cgProblem({ ...ready, scene: "   " }), /Describe/);
  assert.match(cg.cgProblem({ ...ready, scene: "x".repeat(cg.CG_SCENE_LIMIT + 1) }), /shorter/);
  assert.deepEqual(cg.cgRequest(ready), {
    scene: "Quen sitting on the couch at night",
    characters: [{ character_id: "quen", reference_asset_id: "a" }],
    count: cg.CG_COUNT,
  });
});

test("a second character stands on the right and needs its own approved image", () => {
  const two = { picks: [{ character: "quen", reference: "a" }, { character: "lina", reference: "b" }], scene: "on a couch" };
  assert.equal(cg.cgProblem(two), null);
  assert.deepEqual(cg.cgRequest(two).characters, [
    { character_id: "quen", reference_asset_id: "a" }, { character_id: "lina", reference_asset_id: "b" },
  ]);
  assert.match(cg.cgProblem({ ...two, picks: [two.picks[0], { character: "quen", reference: "a" }] }), /two different/);
  assert.match(cg.cgProblem({ ...two, picks: [two.picks[0], { character: "lina", reference: null }] }), /Approve/);
  assert.match(cg.cgProblem({ ...two, picks: [...two.picks, { character: "mira", reference: "c" }] }), /two/);
  assert.equal(cg.CG_MAX_CHARACTERS, 2);
  // Two characters are experimental: say so, and start two jobs of four by default.
  assert.equal(cg.TWO_CHARACTER_NOTE,
    "Experimental: the two characters may swap hair or clothes. Generate a few and keep the best.");
  assert.equal(cg.cgJobCount(two.picks), 2);
  assert.equal(cg.cgJobCount([two.picks[0]]), 1);
  assert.equal(cg.cgCandidates(two.picks), 2 * cg.CG_COUNT);
  assert.equal(cg.cgCandidates([two.picks[0]]), cg.CG_COUNT);
  // The second picker offers everyone but the first character.
  assert.deepEqual(cg.otherCharacters(["mira", "quen", "lina"], "quen"), ["mira", "lina"]);
});

test("CG jobs read as CGs and explain a worker without the identity adapter", () => {
  const job = { purpose: "scene_art", status: "completed", transparent: false, assets: [{}, {}], cancel_requested: false };
  assert.equal(characters.jobStatus(job), "2 CGs ready");
  assert.match(characters.jobStatus({ ...job, status: "failed", error_code: "ip_adapter_unavailable" }), /IP-Adapter/);
  assert.equal(characters.jobStatus({ ...job, status: "running", progress: 1, count: 4 }), "Generated 1 of 4…");
});

test("a CG job names every character it draws", () => {
  const names = { quen: "Quen Aldwinia", lina: "Lina" };
  const two = { character_id: "quen", reference_assets: [{ character_id: "quen" }, { character_id: "lina" }] };
  assert.equal(cg.cgSubject(two, names), "Quen Aldwinia and Lina");
  assert.equal(cg.cgSubject({ character_id: "mira", reference_assets: null }, names), "mira");
});
