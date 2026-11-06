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
