import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function load(name) {
  const source = await readFile(new URL(`../src/narrative/${name}.ts`, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
  return import(`data:text/javascript;base64,${Buffer.from(outputText + `\n//# sourceURL=${name}.js`).toString("base64")}`);
}
const model = await load("expressionModel");

test("result previews show a square around the face, kept inside the image", () => {
  // A 100 px face in an 800 x 1200 sprite: a 160 px square centred on it.
  const view = model.faceView([350, 40, 450, 140], 800, 1200);
  assert.equal(view.width, 500);
  assert.equal(view.left, -(320 / 160) * 100);
  assert.equal(view.top, -(10 / 160) * 100);
  // At the top-left corner the square stops at the image edge.
  const corner = model.faceView([0, 0, 100, 100], 800, 1200);
  assert.deepEqual([corner.left, corner.top], [-0, -0]);
  // A face box larger than the image shows the whole short side.
  assert.ok(Math.abs(model.faceView([0, 0, 800, 800], 800, 600).width - 100 * 800 / 600) < 1e-9);
});

function figure(width, height, paint) {
  const alpha = new Uint8Array(width * height);
  paint((x0, y0, x1, y1) => {
    for (let y = y0; y < y1; y += 1) for (let x = x0; x < x1; x += 1) alpha[y * width + x] = 255;
  });
  return alpha;
}

test("the first guess puts the box on the head of a transparent figure", () => {
  // A figure from row 20 to 299: head centred at x=100 above a wider body.
  const alpha = figure(200, 320, fill => { fill(80, 20, 120, 60); fill(50, 60, 150, 300); });
  const box = model.faceBoxFromAlpha(alpha, 200, 320);
  const size = Math.round(280 * 0.11);
  assert.equal(box[2] - box[0], size);
  assert.equal(box[3] - box[1], size);
  assert.ok(Math.abs((box[0] + box[2]) / 2 - 100) <= 1);
  assert.ok(Math.abs((box[1] + box[3]) / 2 - (20 + 280 * 0.075)) <= 1);
});

test("opaque images get a portrait-style guess inside the image", () => {
  const alpha = new Uint8Array(300 * 400).fill(255);
  const box = model.faceBoxFromAlpha(alpha, 300, 400);
  assert.deepEqual(box, [105, 35, 195, 125]);
});

test("boxes stay inside the image and at least the minimum size", () => {
  assert.deepEqual(model.clampBox([-20, -5, 10, 30], 100, 100), [0, 0, 30, 35]);
  assert.deepEqual(model.clampBox([90, 90, 92, 92], 100, 100), [84, 84, 100, 100]);
  assert.deepEqual(model.moveBox([10, 10, 40, 40], 100, 0, 100, 100), [70, 10, 100, 40]);
  assert.deepEqual(model.resizeBox([10, 10, 40, 40], 20, 5, 100, 100), [10, 10, 60, 60]);
  assert.deepEqual(model.resizeBox([10, 10, 40, 40], -100, -100, 100, 100), [10, 10, 26, 26]);
});

test("expression names follow the server's rules and keys", () => {
  assert.equal(model.validExpression(" Fond  of tea "), true);
  for (const bad of ["", "<b>", "x".repeat(41), "-dash"]) assert.equal(model.validExpression(bad), false);
  assert.equal(model.expressionKey("Fond of tea"), "fond_of_tea");
  assert.equal(model.expressionKey("3 am"), "e_3_am");
  assert.ok(model.EXPRESSION_PRESETS.includes("embarrassed"));
});
