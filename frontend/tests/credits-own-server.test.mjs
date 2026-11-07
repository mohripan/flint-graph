import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/site/creditsModel.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } });
const model = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

const prices = { "image.standard": { credits: 2, kind: "image", label: "Standard image", unit: "image", per: 1 } };
const own = (extra = {}) => ({ mode: "open", is_admin: false, unlimited: true, own_server: true, credits: null, credits_used: 40, prices, ...extra });
const invited = credits => ({ mode: "invite", is_admin: false, unlimited: false, own_server: false, credits, prices });

test("on your own server it says Unlimited, in either mode", () => {
  assert.equal(model.balanceLabel(own()), "Unlimited");
  assert.equal(model.balanceLabel(own({ mode: "invite", is_admin: true })), "Unlimited");
  assert.equal(model.ownServer(own()), true);
});

test("a card tells you what it would cost anyone, and that it is free for you", () => {
  assert.deepEqual(model.quoteView(own(), [["image.standard", 10]]), { text: "20 credits · free for you", over: false });
});

test("the cost beside a button still shows, and never says there are not enough", () => {
  assert.deepEqual(model.partsCostView(own(), [["image.standard", 2]]), { cost: 4, over: false, text: "4 credits" });
  assert.equal(model.costView(own(), "image.standard", 1).text, "2 credits");
  assert.equal(model.unitPrice(own(), "image.standard"), "2 credits per image");
});

test("invited people still see their balance and what they cannot afford", () => {
  assert.equal(model.partsCostView(invited(1), [["image.standard", 2]]).over, true);
  assert.equal(model.quoteView(invited(1), [["image.standard", 2]]).over, true);
  assert.equal(model.balanceLabel(invited(100)), "100 credits");
  assert.equal(model.ownServer(invited(100)), false);
});

test("an older API and an unlimited key stay as they were", () => {
  const older = { mode: "open", is_admin: false, unlimited: true, credits: null, prices };
  assert.equal(model.balanceLabel(older), null);
  assert.equal(model.partsCostView(older, [["image.standard", 2]]), null);
  assert.equal(model.quoteView(older, [["image.standard", 2]]).text, "4 credits · free for you");
  const unlimitedKey = { mode: "invite", is_admin: false, unlimited: true, own_server: false, credits: 0, prices };
  assert.equal(model.balanceLabel(unlimitedKey), "Unlimited");
  assert.equal(model.partsCostView(unlimitedKey, [["image.standard", 2]]), null);
  assert.equal(model.ownServer(null), false);
});
