import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function load(path) {
  const source = await readFile(new URL(path, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } });
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
}
const routes = await load("../src/site/siteRoutes.ts");
const usage = await load("../src/site/usageModel.ts");
const howItWorks = await load("../src/site/howItWorksContent.ts");

test("How it works steps are complete and their screenshots exist", async () => {
  const titles = howItWorks.STEPS.map(step => step.title);
  assert.equal(new Set(titles).size, titles.length);
  for (const step of howItWorks.STEPS) {
    assert.ok(step.title.trim() && step.body.length > 0 && step.body.every(text => text.trim()), step.title);
    if (!step.image) continue;
    assert.ok(step.image.alt.trim(), `${step.title} needs alt text`);
    assert.match(step.image.src, /^\/site\/[\w-]+\.webp$/);
    await readFile(new URL(`../public${step.image.src}`, import.meta.url));
  }
  assert.ok(howItWorks.FAQ.every(([question, answer]) => question.trim() && answer.trim()));
});

test("public pages, the Studio and old Studio links each get their route", () => {
  assert.equal(routes.routeFor("/", ""), "home");
  assert.equal(routes.routeFor("/how-it-works", ""), "how");
  assert.equal(routes.routeFor("/how-it-works/", ""), "how");
  assert.equal(routes.routeFor("/join", "?key=FG-AAAA"), "join");
  assert.equal(routes.routeFor("/studio", "?project=1"), "studio");
  // Links made before the public pages, and sign-in callbacks, still open the Studio.
  assert.equal(routes.routeFor("/", "?project=abc&thread=t"), "studio");
  assert.equal(routes.routeFor("/", "?code=x&state=y"), "studio");
  assert.equal(routes.routeFor("/", "?code=x"), "home");
  assert.equal(routes.routeFor("/nowhere", ""), "home");
});

test("sign-in only returns to same-origin paths", () => {
  assert.equal(routes.safeReturn("/join?key=FG-1"), "/join?key=FG-1");
  for (const bad of ["https://evil.example/", "//evil.example", "javascript:alert(1)", 42, undefined])
    assert.equal(routes.safeReturn(bad), "/studio");
});

test("usage rows, amounts and invitation states read plainly", () => {
  const rows = usage.usageRows({ image: { daily: 40, total: 300 }, training: { total: 0 } },
    { image: { day: 3, total: 12 } });
  assert.deepEqual(rows.map(row => row.kind), ["image", "voice", "assistant", "release", "training"]);
  assert.equal(usage.amount(rows[0].day, rows[0].daily), "3 of 40");
  assert.equal(usage.amount(rows[1].day, rows[1].daily), "0");
  assert.equal(usage.amount(0, rows[4].totalLimit), "not included");
  const now = Date.parse("2026-11-06T00:00:00Z");
  const base = { revoked_at: null, expires_at: null, redemption_count: 0, max_redemptions: 1 };
  assert.equal(usage.invitationState(base, now), "active");
  assert.equal(usage.invitationState({ ...base, redemption_count: 1 }, now), "used");
  assert.equal(usage.invitationState({ ...base, expires_at: "2026-11-05T00:00:00Z" }, now), "expired");
  assert.equal(usage.invitationState({ ...base, revoked_at: "2026-11-01T00:00:00Z" }, now), "revoked");
});

test("the allowance form round-trips and refuses anything but whole numbers", () => {
  const limits = { image: { daily: 40, total: 300 }, voice: { total: 5 } };
  assert.deepEqual(usage.parseLimits(usage.limitsForm(limits)), limits);
  assert.deepEqual(usage.parseLimits({ "image.daily": " ", "voice.total": "0" }), { voice: { total: 0 } });
  assert.match(usage.parseLimits({ "image.daily": "1.5" }), /Images: use a whole number/);
  assert.match(usage.parseLimits({ "release.total": "-1" }), /Release builds/);
  assert.match(usage.invitationMessage("https://x.example/join?key=FG-1", "FG-1"), /enter this key:\nFG-1/);
  assert.match(usage.invitationMessage("https://x.example/join", null), /sign in with this email address/);
});

const credits = await load("../src/site/creditsModel.ts");
const PRICES = {
  "image.standard": { credits: 2, kind: "image", label: "Standard image", unit: "image", per: 1 },
  "image.sprite": { credits: 3, kind: "image", label: "Transparent sprite", unit: "image", per: 1 },
  "image.high_res": { credits: 5, kind: "image", label: "High-resolution image", unit: "image", per: 1 },
  "training.character": { credits: 25, kind: "training", label: "Character training", unit: "100 training steps", per: 100 },
  "release.build": { credits: 25, kind: "release", label: "Release build", unit: "build", per: 1 },
};
const invited = (changes = {}) => ({ mode: "invite", has_access: true, is_admin: false, status: "active",
  credits: 30, unlimited: false, prices: PRICES, ...changes });

test("the Studio mirrors the server's price items", () => {
  assert.equal(credits.imageItem({ purpose: "background" }), "image.standard");
  assert.equal(credits.imageItem({ purpose: "character_portrait", transparent: true }), "image.sprite");
  assert.equal(credits.imageItem({ purpose: "character_portrait", transparent: true, hires: true }), "image.high_res");
  assert.equal(credits.imageItem({ purpose: "character_expression" }), "image.expression");
  assert.equal(credits.imageItem({ purpose: "scene_art" }), "image.cg");
  assert.equal(credits.imageItem({ purpose: "character_portrait", pose: true }), "image.pose");
  assert.equal(credits.imageItem({ purpose: "character_portrait", pose: true, repair: true }), "image.pose_repair");
  assert.equal(credits.trainingItem({ character: false }), "training.style");
  assert.equal(credits.trainingItem({ character: true, reference: true }), "training.character_reference");
  assert.deepEqual([20, 100, 101, 400].map(credits.trainingBlocks), [1, 1, 2, 4]);
  assert.equal(credits.voiceItem("indextts-2.5"), "voice.indextts-2.5");
  assert.equal(credits.assistantItem("anthropic"), "assistant.anthropic");
});

test("prices show only to people who spend credits, and warn when the balance is short", () => {
  assert.equal(credits.costView(invited(), "image.sprite", 4).text, "12 credits");
  assert.equal(credits.costView(invited(), "image.sprite", 4).over, false);
  const short = credits.costView(invited({ credits: 5 }), "image.sprite", 4);
  assert.equal(short.over, true);
  assert.equal(short.text, "12 credits · you have 5");
  assert.equal(credits.costView(invited(), "release.build", 1).text, "25 credits");
  assert.equal(credits.costView(invited({ credits: 50 }), "training.character", credits.trainingBlocks(200)).text, "50 credits");
  assert.equal(credits.costView(invited({ credits: 1 }), "image.standard", 0), null);
  for (const free of [null, invited({ mode: "open" }), invited({ unlimited: true }), invited({ is_admin: true, unlimited: true }),
    invited({ credits: null })])
    assert.equal(credits.costView(free, "image.sprite", 4), null);
  // A price the server does not list is not guessed.
  assert.equal(credits.costView(invited(), "image.mystery", 1), null);
  // Several speakers, each with their own model, add up.
  assert.equal(credits.partsCostView(invited(), [["image.standard", 2], ["image.sprite", 1], ["image.high_res", 0]]).text, "7 credits");
  assert.equal(credits.partsCostView(invited(), [["image.standard", 2], ["image.mystery", 1]]), null);
  assert.equal(credits.unitPrice(invited(), "image.sprite"), "3 credits per image");
  assert.equal(credits.unitPrice(invited({ unlimited: true }), "image.sprite"), "");
});

test("the balance reads plainly in invite mode only", () => {
  assert.equal(credits.balanceLabel(invited()), "30 credits");
  assert.equal(credits.balanceLabel(invited({ credits: 1 })), "1 credit");
  assert.equal(credits.balanceLabel(invited({ unlimited: true })), "Unlimited");
  assert.equal(credits.balanceLabel(invited({ mode: "open", unlimited: true })), null);
  assert.equal(credits.balanceLabel(invited({ credits: null })), null);
  assert.equal(credits.balanceLabel(null), null);
  // An API from before credits sends neither field.
  const older = invited({ credits: undefined, unlimited: undefined });
  assert.equal(credits.balanceLabel(older), null);
  assert.equal(credits.costView(older, "image.sprite", 1), null);
});

test("paid requests and usage errors reload the balance", () => {
  const project = "/v1/narrative/projects/p1";
  for (const path of [`${project}/assets/background-jobs`, `${project}/characters/mira/portrait-jobs`,
    `${project}/characters/mira/looks/pose-jobs`, `${project}/characters/mira/looks/pose-repairs`,
    `${project}/look-scene-art-jobs`, `${project}/characters/mira/voice-jobs`, `${project}/style-jobs`,
    `${project}/assistant/threads/t1/turns`, `${project}/releases`, `${project}/assistant/proposals/x/image-actions/2`])
    assert.equal(credits.paidRequest("POST", path), true, path);
  assert.equal(credits.paidRequest("GET", `${project}/style-jobs`), false);
  assert.equal(credits.paidRequest("POST", `${project}/style-jobs/j1/cancel`), false);
  assert.equal(credits.paidRequest("POST", `${project}/revisions`), false);
  assert.equal(credits.usageProblem("urn:flint-graph:error:out-of-credits"), true);
  assert.equal(credits.usageProblem("urn:flint-graph:error:usage-limit"), true);
  assert.equal(credits.usageProblem("urn:flint-graph:error:conflict"), false);
  assert.equal(credits.usageProblem(undefined), false);
});

test("ledger entries and operator changes read as sentences", () => {
  const charge = { change: "charge", amount: -12, balance: 18, item: "image.sprite", quantity: 4, note: null, actor_email: null };
  assert.equal(credits.ledgerText(charge, PRICES), "4 × Transparent sprite");
  assert.equal(credits.ledgerText({ ...charge, item: "training.character", quantity: 2 }, PRICES), "Character training");
  assert.equal(credits.ledgerText({ ...charge, item: "voice.gone", quantity: 1 }, PRICES), "voice.gone");
  assert.equal(credits.ledgerText({ change: "join", amount: 30, item: null, quantity: null, note: null, actor_email: null }, PRICES), "Joined");
  assert.equal(credits.ledgerText({ change: "add", amount: 100, item: null, quantity: null, note: "Pilot week", actor_email: "boss@example.com" }, PRICES),
    "Added by boss@example.com: Pilot week");
  assert.equal(credits.ledgerText({ change: "unlimited", amount: 0, item: null, quantity: null, note: null, actor_email: "boss@example.com" }, PRICES),
    "Made unlimited by boss@example.com");
  assert.equal(credits.signed(-12), "−12");
  assert.equal(credits.signed(100), "+100");
  assert.equal(credits.signed(0), "0");
  assert.deepEqual(credits.parseCreditChange("add", " 25 "), { change: "add", amount: 25 });
  assert.match(credits.parseCreditChange("add", "0"), /at least 1/);
  assert.match(credits.parseCreditChange("remove", "x"), /whole number/);
  assert.deepEqual(credits.parseCreditChange("set", "0"), { change: "set", amount: 0 });
  assert.match(credits.parseCreditChange("set", "10000001"), /at most/);
});
