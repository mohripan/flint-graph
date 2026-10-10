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
const evaluate = (script) => JSON.parse(run("eval", "--base64", Buffer.from(script).toString("base64")).trim());
const completed = {
  id: "saved-run", tenant_id: "qa-workspace", query_text: "Reopen the long research answer",
  status: "completed", answer_text: Array.from({ length: 60 }, (_, n) => `Paragraph ${n + 1}: synthetic research [c1].`).join("\n\n") + "\nFINAL ANSWER LINE",
  abstained: false, abstain_reason: null, error_code: null, error_message: null,
  created_at: "2026-10-10T01:00:00Z", query_diagnostics: {
    retrieved_candidate_count: 30, context_record_count: 24, context_token_count: 8000,
    support_status_counts: { supported: 6 }, answer_provider: "test", support_provider: "test",
  },
};
const provenance = {
  query_run_id: completed.id, answer_text: null, abstained: false,
  supported_claim_count: 6, unsupported_claim_count: 0,
  answer_provider: "test", citations: Array.from({ length: 24 }, (_, n) => ({
    citation_id: `c${n + 1}`, text: `Source ${n + 1}: synthetic evidence. ` + (n === 23 ? "LongWord".repeat(70) : ""),
    ...(n === 23 ? { metadata: { title: "LongReportTitle".repeat(35) } } : {}), claims: [],
  })),
};

try {
  route("**/v1/workspaces", [
    { id: "qa-workspace", name: "Migration QA", role: "owner" },
    { id: "qa-other", name: "Separate QA workspace", role: "owner" },
  ]);
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
  run("network", "unroute", "**/v1/query-runs");
  route("**/v1/query-runs?**", [completed]);
  route("**/v1/query-runs", [completed]);
  route("**/v1/query-runs/saved-run", completed);
  route("**/v1/query-runs/saved-run/provenance", provenance);
  run("reload");
  run("wait", "--fn", "document.body.textContent.includes('Reopen the long research answer')");
  run("find", "text", "Question history", "click", "--exact");
  evaluate(`window.qaPosts = 0; const fetchOriginal = window.fetch; window.fetch = (...args) => {
    if (args[1]?.method === 'POST') window.qaPosts++; return fetchOriginal(...args);
  }; true`);
  run("find", "role", "button", "click", "--name", "Reopen the long research answer", "--exact");
  run("wait", "1000");
  assert.ok(evaluate("document.body.textContent.includes('FINAL ANSWER LINE')"), "History must reopen the saved answer, not just copy its question");
  assert.equal(evaluate("window.qaPosts"), 0, "Reopening history must not create another query");
  for (const width of [390, 1280]) {
    run("set", "viewport", String(width), "900");
    const layout = evaluate(`(() => {
      const page = document.querySelector('[aria-label="Ask workspace"]');
      const answer = document.querySelector('[aria-label="Answer"]');
      const diagnostics = document.querySelector('details[data-diagnostics]');
      return { width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
        pageScrollable: page && page.scrollHeight > page.clientHeight,
        answerHeight: answer?.getBoundingClientRect().height,
        answerScroll: answer && getComputedStyle(answer).overflowY,
        collapsed: diagnostics && !diagnostics.open,
        answerBeforeDiagnostics: !!answer && !!diagnostics && !!(answer.compareDocumentPosition(diagnostics) & Node.DOCUMENT_POSITION_FOLLOWING),
        sourceScroll: getComputedStyle(document.getElementById('citation-c24').parentElement).overflowY,
      };
    })()`);
    assert.ok(layout.scrollWidth <= width + 1, `Results overflow horizontally at ${width}px: ${JSON.stringify(layout)}`);
    assert.ok(layout.pageScrollable, "The whole Ask page must scroll");
    assert.ok(layout.answerHeight > 1200, `Long answer must not shrink to a tiny pane: ${JSON.stringify(layout)}`);
    assert.ok(["visible", "clip"].includes(layout.answerScroll), "Answer must use the primary page scroll");
    assert.ok(["visible", "clip"].includes(layout.sourceScroll), "Sources must use the primary page scroll");
    assert.ok(layout.collapsed && layout.answerBeforeDiagnostics, "Diagnostics must start collapsed after the answer");
    assert.ok(evaluate(`(() => {
      const page = document.querySelector('[aria-label="Ask workspace"]');
      const last = document.getElementById('citation-c24'); last.scrollIntoView({block:'center'});
      const r = last.getBoundingClientRect(), p = page.getBoundingClientRect();
      return r.top >= p.top - 1 && r.bottom <= p.bottom + 1;
    })()`), "The last citation must be reachable in the page viewport");
    console.log(`Saved answer and primary scrolling passed at ${width}px`);
  }
  run("find", "text", "Run diagnostics", "click", "--exact");
  assert.ok(evaluate("document.querySelector('details[data-diagnostics]').open"), "Diagnostics expand on request");
  // More complex HTTP fixtures are generated in the browser to avoid Windows'
  // command-line size limits. Only the fetch boundary is mocked, not React state.
  evaluate(`(() => {
    const original = window.fetch;
    window.qaHistoryRequests = [];
    window.fetch = async (input, init) => {
      const u = new URL(input, location.origin);
      const headers = new Headers(init?.headers);
      const tenant = headers.get('X-Tenant-ID');
      const json = body => new Response(JSON.stringify(body), {status:200,headers:{'Content-Type':'application/json'}});
      const saved = {id:'older-run',tenant_id:'qa-workspace',query_text:'An older needle question',status:'completed',
        answer_text:'An older saved answer.',created_at:'2025-01-01T00:00:00Z',query_diagnostics:{}};
      if (u.pathname === '/v1/query-runs') {
        window.qaHistoryRequests.push(u.search);
        if (tenant !== 'qa-workspace') return json([]);
        if (u.searchParams.get('q') === 'missing') return json([]);
        if (u.searchParams.get('q') === 'needle' || u.searchParams.has('before_id')) return json([saved]);
        return json(Array.from({length:25}, (_,n) => ({...saved,id:n===0?'failed-run':n===1?'abstained-run':n===2?'slow-run':n===3?'pending-run':'page-'+n,
          query_text:n===0?'Failed saved question':n===1?'Abstained saved question':n===2?'Slow saved question':n===3?'Pending saved question':'Saved question '+n,
          status:n===0?'failed':n===3?'running':'completed'})));
      }
      if (u.pathname.startsWith('/v1/query-runs/')) {
        const id = u.pathname.split('/')[3];
        if (u.pathname.endsWith('/provenance')) return json({answer_text:id==='abstained-run'?null:saved.answer_text,
          abstained:id==='abstained-run',abstain_reason:'Synthetic insufficient evidence.',citations:[],supported_claim_count:0,unsupported_claim_count:0});
        if (id==='slow-run') await new Promise(resolve=>setTimeout(resolve,1800));
        return json({...saved,id,query_text:id==='slow-run'?'Slow saved question':saved.query_text,
          status:id==='failed-run'?'failed':id==='pending-run'?'running':'completed',
          answer_text:id==='slow-run'?'STALE WORKSPACE ANSWER':id==='abstained-run'?null:saved.answer_text,
          error_message:'Synthetic provider failure.'});
      }
      return original(input, init);
    };
    return true;
  })()`);
  run("find", "role", "button", "click", "--name", "Refresh history", "--exact");
  run("find", "text", "Question history", "click", "--exact");
  run("wait", "--fn", "document.body.textContent.includes('Saved question 24')");
  run("find", "role", "button", "click", "--name", "Load older questions", "--exact");
  run("wait", "--fn", "document.body.textContent.includes('An older needle question')");
  assert.ok(evaluate("window.qaHistoryRequests.some(q => new URLSearchParams(q).get('before_id') === 'page-24')"), "History loads older results using a cursor");
  run("find", "role", "button", "click", "--name", "An older needle question", "--exact");
  run("wait", "--fn", "document.body.textContent.includes('An older saved answer.')");
  for (const [name, message] of [
    ["Failed saved question", "Synthetic provider failure."],
    ["Abstained saved question", "Synthetic insufficient evidence."],
    ["Pending saved question", "This saved question is running."],
  ]) {
    run("find", "text", "Question history", "click", "--exact");
    run("find", "role", "button", "click", "--name", name, "--exact");
    run("wait", "--fn", `document.body.textContent.includes(${JSON.stringify(message)})`);
  }
  run("find", "text", "Question history", "click", "--exact");
  run("find", "role", "searchbox", "fill", "--name", "Search questions", "needle");
  run("wait", "--fn", "window.qaHistoryRequests.some(q => new URLSearchParams(q).get('q') === 'needle')");
  assert.equal(evaluate("document.querySelectorAll('details li').length"), 1, "History search replaces the loaded page");
  run("find", "role", "searchbox", "fill", "--name", "Search questions", "missing");
  run("wait", "--fn", "document.body.textContent.includes('No matching questions.')");
  run("find", "role", "searchbox", "click", "--name", "Search questions");
  run("press", "Control+A");
  run("press", "Backspace");
  run("wait", "--fn", "document.body.textContent.includes('Slow saved question')");
  run("find", "role", "button", "click", "--name", "Slow saved question", "--exact");
  run("select", 'select[aria-label="Workspace"]', "qa-other");
  run("wait", "2000");
  assert.ok(evaluate("!document.querySelector('[aria-label=Answer]') && !document.body.textContent.includes('STALE WORKSPACE ANSWER')"), "A delayed previous-workspace response must not restore its answer");
  assert.equal(evaluate("window.qaPosts"), 0, "All history interactions remain read-only");
  console.log("History pagination/search/outcomes and delayed workspace isolation passed");
} finally {
  run("close");
}
