import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/site/creditsModel.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } });
const model = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

const prices = { "image.standard": { credits: 2, kind: "image", label: "Standard image", unit: "image", per: 1 } };
const own = (credits, extra = {}) => ({ mode: "open", is_admin: false, unlimited: true, keeps_going: true, credits, prices, ...extra });
const invited = credits => ({ mode: "invite", is_admin: false, unlimited: false, keeps_going: false, credits, prices });

test("on your own server the balance is a real number, in either mode", () => {
  assert.equal(model.balanceLabel(own(744)), "744 credits");
  assert.equal(model.balanceLabel(own(1)), "1 credit");
  assert.equal(model.balanceLabel(own(0)), "0 credits");
  assert.equal(model.balanceLabel(own(50, { mode: "invite", is_admin: true })), "50 credits");
});

test("a card shows the price and the balance, and is never refused", () => {
  assert.deepEqual(model.quoteView(own(744), [["image.standard", 10]]), { text: "20 credits · you have 744", over: false });
  assert.deepEqual(model.quoteView(own(0), [["image.standard", 10]]), { text: "20 credits · you have 0", over: false });
});

test("the cost beside a button shows too, without saying there are not enough", () => {
  assert.deepEqual(model.partsCostView(own(0), [["image.standard", 2]]), { cost: 4, over: false, text: "4 credits" });
  assert.equal(model.costView(own(744), "image.standard", 1).text, "2 credits");
  assert.equal(model.unitPrice(own(744), "image.standard"), "2 credits per image");
});

test("invited people still see what they cannot afford", () => {
  assert.equal(model.partsCostView(invited(1), [["image.standard", 2]]).over, true);
  assert.equal(model.quoteView(invited(1), [["image.standard", 2]]).over, true);
  assert.equal(model.balanceLabel(invited(1)), "1 credit");
});

test("an older API, an unlimited key and open mode without a balance stay as they were", () => {
  const older = { mode: "open", is_admin: false, unlimited: true, credits: null, prices };
  assert.equal(model.balanceLabel(older), null);
  assert.equal(model.partsCostView(older, [["image.standard", 2]]), null);
  assert.equal(model.quoteView(older, [["image.standard", 2]]).text, "4 credits · free for you");
  const unlimitedKey = { mode: "invite", is_admin: false, unlimited: true, keeps_going: false, credits: 0, prices };
  assert.equal(model.balanceLabel(unlimitedKey), "Unlimited");
  assert.equal(model.quoteView(unlimitedKey, [["image.standard", 2]]).text, "4 credits · free for you");
  assert.equal(model.keepsGoing(unlimitedKey), false);
  assert.equal(model.keepsGoing(own(0)), true);
  assert.equal(model.keepsGoing(null), false);
});
