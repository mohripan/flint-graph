import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";

// Optional developer check: start Vite first. Mock only the public HTTP boundary.
// Pin the browser CLI rather than resolving an unreviewed latest on every run.
const baseUrl = new URL(process.env.FLINT_GRAPH_BROWSER_URL ?? "http://127.0.0.1:5173");
assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(baseUrl.hostname));
assert.ok(process.env.npm_execpath, "Run this check with npm run test:browser");
const session = `flintgraph-responsive-${process.pid}`;
let starting = true;
const run = (...args) => {
  // The browser daemon must not inherit a captured pipe on its first launch:
  // Windows otherwise waits for the long-lived daemon to close that pipe.
  const stdio = starting ? ["ignore", "inherit", "inherit"] : ["ignore", "pipe", "pipe"];
  starting = false;
  return execFileSync(process.execPath, [
  process.env.npm_execpath, "exec", "--yes", "--package=agent-browser@0.39.0", "--",
  "agent-browser", "--session", session, ...args,
  ], { encoding: "utf8", windowsHide: true, timeout: 60000, stdio });
};
const route = (pattern, body) => run("network", "route", pattern, "--body", JSON.stringify(body));

try {
  route("**/v1/workspaces", [{ id: "qa-workspace", name: "Migration QA", role: "owner" }]);
  route("**/v1/search-readiness**", {
    ready: true, reason: "searchable_content_available", active_index_version: null,
    completed_coverage_count: 1, running_coverage_count: 0, failed_coverage_count: 0,
    cancelled_coverage_count: 0, documents: [],
  });
  route("**/v1/query-runs", []);
  route("**/health/ready", { status: "ok" });
  run("open", baseUrl.href);
  run("wait", "--fn", "document.querySelector('textarea') !== null");
  for (const width of [390, 1280]) {
    run("set", "viewport", String(width), "900");
    const script = `JSON.stringify({
      width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
      inputWidth: document.querySelector('textarea').getBoundingClientRect().width,
      clippedControls: [...document.querySelectorAll('header button, header select, nav button')]
        .filter(el => { const r = el.getBoundingClientRect(); return r.left < 0 || r.right > innerWidth + 1; })
        .map(el => el.textContent.trim())
    })`;
    const raw = run("eval", "--base64", Buffer.from(script).toString("base64"));
    const layout = JSON.parse(JSON.parse(raw.trim()));
    assert.ok(layout.scrollWidth <= width + 1, `Horizontal overflow at ${width}px: ${raw}`);
    assert.ok(layout.inputWidth >= (width < 640 ? width * 0.75 : 700), `Crowded Ask input: ${raw}`);
    assert.deepEqual(layout.clippedControls, [], `Clipped navigation at ${width}px`);
    console.log(`Responsive shell passed at ${width}px`);
  }
} finally {
  run("close");
}
