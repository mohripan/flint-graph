import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function load(name) {
  const source = await readFile(new URL(`../src/narrative/${name}.ts`, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
  return import(`data:text/javascript;base64,${Buffer.from(outputText + `\n//# sourceURL=${name}.js`).toString("base64")}`);
}
const stage = await load("stageModel");

const sha = seed => seed.repeat(64).slice(0, 64);
const line = (text, next, extra = {}) => ({ type: "line", text_id: `${text.length}_${next}`, text, next, ...extra });
function story() {
  return {
    schema_version: "2", id: "harbor", title: "Harbor", language: "en", entry: "opening",
    characters: {
      mira: { name: "Mira", sprites: { neutral: "mira_neutral", happy: "mira_happy" } },
      oren: { name: "Oren", sprites: { neutral: "oren_neutral" } },
    },
    variables: {},
    assets: {
      mira_neutral: { kind: "image", path: "assets/mira_neutral.png", sha256: sha("1") },
      mira_happy: { kind: "image", path: "assets/mira_happy.png", sha256: sha("2") },
      oren_neutral: { kind: "image", path: "assets/oren_neutral.png", sha256: sha("3") },
    },
    nodes: {
      opening: line("Fog.", "pier", { speaker: "mira" }),
      pier: { type: "choice", text_id: "pier", text: "Go?", options: [
        { id: "go", text_id: "go", text: "Go", target: "end" }, { id: "stay", text_id: "stay", text: "Stay", target: "opening" }] },
      end: { type: "end", text_id: "end", text: "Fin", ending: "done" },
    },
  };
}

test("library files bind once per file under a valid unique story asset ID", () => {
  const dusk = { sha256: sha("a"), media_type: "image/png", name: "Harbor at Dusk (v2)" };
  const first = stage.bindAsset(story(), dusk);
  assert.equal(first.key, "harbor_at_dusk_v2");
  assert.deepEqual(first.story.assets.harbor_at_dusk_v2, { kind: "image", path: "assets/harbor_at_dusk_v2.png", sha256: sha("a") });
  assert.equal(stage.bindAsset(first.story, dusk).story, first.story, "same bytes reuse the same key");
  const twin = stage.bindAsset(first.story, { ...dusk, sha256: sha("b") });
  assert.equal(twin.key, "harbor_at_dusk_v2_2");
  const font = stage.bindAsset(story(), { sha256: sha("c"), media_type: "font/otf", name: "9 Old Type" });
  assert.equal(font.key, "asset_9_old_type");
  assert.equal(font.story.assets[font.key].path, "assets/asset_9_old_type.otf");
  assert.equal(stage.bindAsset(story(), { sha256: sha("d"), media_type: "image/png", name: "CON" }).key, "asset_con");
  assert.throws(() => stage.bindAsset(story(), { sha256: sha("e"), media_type: "image/jpeg", name: "x" }));
});

test("theme fields equal to the defaults stay out of the story; fonts bind and unbind", () => {
  let value = stage.setThemeValue(story(), "textbox", "position", "top");
  assert.deepEqual(value.theme, { textbox: { position: "top" } });
  value = stage.setThemeValue(value, "textbox", "position", "bottom");
  assert.equal("theme" in value, false);
  const font = stage.bindAsset(value, { sha256: sha("f"), media_type: "font/ttf", name: "Old Type" });
  value = stage.setThemeValue(font.story, "font", "asset", font.key);
  assert.equal(value.theme.font.asset, "old_type");
  assert.ok(value.assets.old_type);
  value = stage.resetTheme(value);
  assert.equal("theme" in value, false);
  assert.equal("old_type" in value.assets, false, "unused fonts are pruned");
  assert.equal(stage.resolvedTheme(story()).textbox.width, 92);
  assert.deepEqual(stage.splitColor("#182635e6"), { rgb: "#182635", alpha: 230 });
  assert.equal(stage.joinColor("#ABCDEF", 255), "#abcdef");
  assert.equal(stage.joinColor("#abcdef", 15), "#abcdef0f");
  assert.equal(stage.inkOn("#d5ae68"), "#182635");
  assert.equal(stage.inkOn("#2a1b3c"), "#f0f4f6");
});

test("a scene's stage step keeps the scene ID, routes and entry, and folds back when emptied", () => {
  const dusk = stage.bindAsset(story(), { sha256: sha("a"), media_type: "image/png", name: "Dusk" });
  const edit = { background: dusk.key, show: [{ character: "mira", sprite: "neutral", position: "left" }], hide: [] };
  const staged = stage.setSceneStage(dusk.story, "opening", edit);
  assert.equal(staged.entry, "opening");
  assert.equal(staged.nodes.opening.type, "stage");
  assert.equal(staged.nodes.opening.next, "opening_open");
  assert.equal(staged.nodes.opening_open.text, "Fog.");
  assert.equal(staged.nodes.pier.options[1].target, "opening", "loops back through the stage step");
  assert.deepEqual(stage.sceneStage(staged, "opening"), edit);
  const updated = stage.setSceneStage(staged, "opening", { show: [], hide: ["oren"] });
  assert.deepEqual(updated.nodes.opening, { type: "stage", hide: ["oren"], next: "opening_open" });
  assert.equal("dusk" in updated.assets, false, "a background no longer used is pruned");
  const cleared = stage.setSceneStage(updated, "opening", { show: [], hide: [] });
  assert.deepEqual(cleared.nodes, story().nodes);
  assert.equal(stage.setSceneStage(story(), "opening", { show: [], hide: [] }).nodes.opening.type, "line");
  for (const bad of [
    { show: [edit.show[0], edit.show[0]], hide: [] },
    { show: [edit.show[0], { character: "oren", sprite: "neutral", position: "left" }], hide: [] },
    { show: [edit.show[0]], hide: ["mira"] },
  ]) assert.throws(() => stage.setSceneStage(story(), "opening", bad));
});

test("the inherited stage follows every path and marks disagreement as varying", () => {
  const value = story();
  value.entry = "start";
  value.nodes.start = { type: "stage", background: "mira_neutral", show: [{ character: "mira", sprite: "neutral", position: "left" }], next: "opening" };
  value.nodes.opening = line("Fog.", "pier", { speaker: "mira", expression: "happy" });
  value.nodes.pier.options[1].target = "late";
  value.nodes.late = { type: "stage", hide: ["mira"], show: [{ character: "oren", sprite: "neutral", position: "center" }], next: "after" };
  value.nodes.after = line("Later.", "end");
  value.nodes.pier.options[0].target = "after";
  const before = stage.stageBefore(value);
  assert.deepEqual(before.get("pier").characters, { mira: { position: "left", sprite: "happy" } });
  assert.deepEqual(before.get("after").characters, { mira: "?", oren: "?" });
  assert.equal(before.get("after").background, "mira_neutral");
  assert.deepEqual(stage.describeSnapshot(value, before.get("after")),
    ["Background mira_neutral", "Mira: varies by path", "Oren: varies by path"]);
  assert.deepEqual(stage.describeSnapshot(value, before.get("start")), ["No background"]);
  assert.deepEqual(stage.describeSnapshot(value, undefined), ["Not reached from the start"]);
});

test("speakers, expressions and sprites stay consistent", () => {
  let value = stage.setLineExpression(story(), "opening", "happy");
  assert.equal(value.nodes.opening.expression, "happy");
  value = stage.setLineSpeaker(value, "opening", "oren");
  assert.equal("expression" in value.nodes.opening, false, "Oren has no happy sprite");
  value = stage.setLineSpeaker(story(), "opening", null);
  assert.equal("speaker" in value.nodes.opening, false);
  assert.throws(() => stage.setLineExpression(value, "opening", "happy"));
  value = stage.setLineExpression(story(), "opening", "happy");
  assert.equal(stage.spriteUses(value, "mira", "happy"), 1);
  assert.throws(() => stage.removeSprite(value, "mira", "happy"), /used once/);
  value = stage.removeSprite(story(), "mira", "happy");
  assert.deepEqual(value.characters.mira.sprites, { neutral: "mira_neutral" });
  assert.equal("mira_happy" in value.assets, false);
  const added = stage.bindAsset(value, { sha256: sha("9"), media_type: "image/png", name: "Mira grin" });
  value = stage.setSprite(added.story, "mira", stage.expressionId(added.story, "mira", "Big Grin!"), added.key);
  assert.equal(value.characters.mira.sprites.big_grin, "mira_grin");
  assert.equal(stage.expressionId(value, "mira", "big grin"), "big_grin_2");
  assert.throws(() => stage.setSprite(value, "mira", "Bad Name", added.key));
  value = stage.setCharacterColor(value, "mira", "#D5AE68");
  assert.equal(value.characters.mira.color, "#d5ae68");
  assert.equal("color" in stage.setCharacterColor(value, "mira", null).characters.mira, false);
});

test("framing mirrors the runtime: fit to the slot by default, or sized from the top and cut off below", () => {
  // A 1:2 sprite fits 92% of the height within 36% of the width, standing on the bottom.
  const fit = stage.figureBox(300, 600, undefined, 20);
  assert.ok(Math.abs(fit.height - 92) < 1e-9 && Math.abs(fit.top - 8) < 1e-9);
  assert.ok(Math.abs(fit.left + fit.width / 2 - 20) < 1e-9);
  // 160% tall from 4% down: the figure continues 64% below the screen.
  const framed = stage.figureBox(300, 600, { scale: 160, top: 4 }, 30);
  assert.equal(framed.height, 160);
  assert.equal(framed.top, 4);
  assert.ok(Math.abs(framed.width - (720 * 1.6 / 2) / 1280 * 100) < 1e-9);
  assert.ok(Math.abs(framed.left + framed.width / 2 - 30) < 1e-9);
  assert.equal(stage.figureBox(300, 600, { scale: 150 }, 50).top, 0, "large figures default to the top edge");
  assert.equal(stage.figureBox(300, 600, { scale: 80 }, 50).top, 20, "small figures default to standing");
  let value = stage.setCharacterFraming(story(), "mira", { scale: 160, top: undefined });
  assert.deepEqual(value.characters.mira.stage, { scale: 160 });
  value = stage.setCharacterFraming(value, "mira", null);
  assert.equal("stage" in value.characters.mira, false);
  assert.throws(() => stage.setCharacterFraming(story(), "mira", { scale: 301 }));
  assert.throws(() => stage.setCharacterFraming(story(), "mira", { top: 12.5 }));
  assert.deepEqual(stage.SLOT_CENTERS, { left: 20, center: 50, right: 80 });
});
