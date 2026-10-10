import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";

const baseUrl = new URL(process.env.FLINT_GRAPH_BROWSER_URL ?? "http://127.0.0.1:5173");
assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(baseUrl.hostname));
assert.ok(process.env.npm_execpath, "Use npm run test:chat-a11y");
const session = `flintgraph-chat-a11y-${process.pid}`;
let starting = true;
const run = (...args) => {
  const stdio = starting ? ["ignore", "inherit", "inherit"] : ["ignore", "pipe", "pipe"];
  starting = false;
  return execFileSync(process.execPath, [process.env.npm_execpath, "exec", "--yes",
    "--package=agent-browser@0.39.0", "--", "agent-browser", "--session", session, ...args],
  { encoding: "utf8", windowsHide: true, timeout: 60000, stdio });
};
const evaluate = (script) => JSON.parse(run("eval", "--base64", Buffer.from(script).toString("base64")).trim());
const route = (pattern, body) => run("network", "route", pattern, "--body", JSON.stringify(body));
const conversation = { id: "a11y-thread", tenant_id: "a11y-workspace", title: "Keyboard research",
  next_turn_number: 3, archived_at: null, created_at: "2026-10-11T00:00:00Z", updated_at: "2026-10-11T00:00:00Z" };
const turn = { id: "a11y-turn", tenant_id: "a11y-workspace", conversation_id: conversation.id,
  turn_number: 1, run: { id: "a11y-run", tenant_id: "a11y-workspace", status: "completed",
    query_text: "What was revenue?", answer_text: "Synthetic grounded answer. [c1]",
    answer_citations: [{citation_id:"c1"}], created_at: conversation.created_at,
    metadata: {conversation_context:{mode:"independent"}} } };
const secondTurn = {...turn,id:"a11y-turn-second",turn_number:2,
  run:{...turn.run,id:"a11y-run-second",query_text:"Another question",answer_text:"Second synthetic answer. [c1]"}};
try {
  route("**/v1/workspaces", [{id:"a11y-workspace",name:"Keyboard fixture",role:"owner"}]);
  route("**/health/ready", {status:"ok"});
  route("**/v1/system-readiness**", {setup_capabilities:{conversation_ledger:true,conversation_discovery:true,prior_year_followups:true}});
  route("**/v1/search-readiness**", {ready:true,reason:"searchable",completed_coverage_count:1,documents:[]});
  route("**/v1/conversations", [conversation]);
  route("**/v1/conversations?**", [conversation]);
  route("**/v1/conversations/a11y-thread", conversation);
  route("**/v1/conversations/a11y-thread/turns**", [turn,secondTurn]);
  run("open", baseUrl.href);
  run("wait", "--fn", "!!document.querySelector('textarea')");
  assert.ok(evaluate("!!document.querySelector('[role=\"region\"][aria-label=\"Conversation transcript\"][tabindex=\"0\"]')"),
    "The keyboard-scrollable transcript must have a valid named region, not an unnamed generic div");
  assert.equal(evaluate("document.querySelector('[aria-label=\"Conversation transcript\"]').getAttribute('aria-live')"), null,
    "Reopening history must not announce the entire transcript as live output");
  console.log("Named keyboard-scrollable transcript region passed");
  evaluate("window.a11yWrites=0;const original=window.fetch;window.fetch=(input,init)=>{if((init?.method&&init.method!=='GET')||String(input).includes('/events/stream'))window.a11yWrites++;return original(input,init)};true");
  const focusButton = (name) => evaluate(`(()=>{const button=[...document.querySelectorAll('button')].find(item=>item.textContent.trim()===${JSON.stringify(name)});if(!button)throw new Error('Missing fixture control');button.focus();return true})()`);
  for (const width of [1280,390]) {
    run("set", "viewport", String(width), "900");
    if(width === 390) {
      focusButton("Conversation history"); run("press", "Enter");
      run("wait", "--fn", "document.querySelector('[aria-controls=\"conversation-sidebar\"]').getAttribute('aria-expanded')==='true'");
    }
    focusButton("Keyboard research"); run("press", "Enter");
    run("wait", "--fn", "document.body.textContent.includes('Synthetic grounded answer.')");
    assert.ok(evaluate("document.activeElement===document.querySelector('h1')"),
      `Explicit keyboard chat selection must focus its heading after content loads at ${width}px`);
    if(width === 390) assert.equal(evaluate("document.querySelector('[aria-controls=\"conversation-sidebar\"]').getAttribute('aria-expanded')"),"false");
    focusButton("New chat"); run("press", "Enter");
    run("wait", "--fn", "document.querySelector('h1').textContent==='New conversation'");
    assert.ok(evaluate("document.activeElement===document.querySelector('textarea')"),
      "New chat must put keyboard focus in the composer without creating a conversation or turn");
    assert.equal(evaluate("document.querySelectorAll('[aria-label^=\"Turn \"]').length"),0);
  }
  assert.equal(evaluate("window.a11yWrites"),0,"Selection and New chat must be read-only until Send");
  evaluate("localStorage.setItem('flintgraph.conversation.a11y-workspace','a11y-thread');true");
  run("reload");
  run("wait", "--fn", "document.body.textContent.includes('Synthetic grounded answer.')");
  assert.ok(evaluate("document.activeElement!==document.querySelector('h1')&&document.activeElement!==document.querySelector('textarea')"),
    "Passive saved-thread restoration must not steal keyboard focus");
  console.log("Desktop/mobile explicit selection and New chat focus; passive restoration passed");
  focusButton("Rename"); run("press", "Enter");
  run("wait", "--fn", "!!document.querySelector('input[maxlength=\"200\"]:not([aria-label])')");
  assert.ok(evaluate("document.activeElement===document.querySelector('input[maxlength=\"200\"]:not([aria-label])')"),
    "Rename begins with focus in its labelled title field");
  focusButton("Cancel rename"); run("press", "Enter");
  assert.ok(evaluate("document.activeElement===[...document.querySelectorAll('button')].find(item=>item.textContent.trim()==='Rename')"),
    "Cancelling rename must restore focus to its trigger, not the page body");
  evaluate(`(()=>{window.renamePayloads=[];const original=window.fetch;window.fetch=async(input,init)=>{
    if(new URL(input,location.origin).pathname==='/v1/conversations/a11y-thread'&&init?.method==='PATCH'){
      const payload=JSON.parse(init.body);window.renamePayloads.push(payload);
      return new Response(JSON.stringify({...${JSON.stringify(conversation)},title:payload.title}),{headers:{'Content-Type':'application/json'}});
    }return original(input,init);
  };return true})()`);
  focusButton("Rename"); run("press", "Enter");
  run("fill", "input[maxlength='200']:not([aria-label])", "Keyboard renamed");
  focusButton("Save title"); run("press", "Enter");
  run("wait", "--fn", "document.querySelector('h1').textContent==='Keyboard renamed'");
  assert.ok(evaluate("document.activeElement===[...document.querySelectorAll('button')].find(item=>item.textContent.trim()==='Rename')"),
    "Saving rename must restore focus after the form is removed");
  assert.deepEqual(evaluate("window.renamePayloads"),[{title:"Keyboard renamed"}]);
  console.log("Keyboard rename focus and title-only write passed");
  route("**/v1/query-runs/a11y-run-second/provenance", {query_run_id:"a11y-run-second",
    supported_claim_count:1,unsupported_claim_count:0,citations:[{citation_id:"c1",context_id:"a11y-source",
      text:"Exact synthetic evidence for the second turn",source_ids:{document_id:"a11y-document"},
      metadata:{title:"Second-turn source"},claims:[{support_status:"supported"}]}]});
  run("focus", "[aria-label='Turn 2'] button"); run("press", "Enter");
  run("wait", "--fn", "!!document.getElementById('a11y-run-second-citation-c1')");
  assert.ok(evaluate("document.activeElement===document.getElementById('a11y-run-second-citation-c1')"),
    "Keyboard citation activation must move focus into its own evidence, not merely scroll");
  assert.equal(evaluate("document.querySelector('[aria-label=\"Sources for turn 1\"]').parentElement.open"),false,
    "A repeated c1 label in an older turn must not receive the focus or evidence expansion");
  run("press", "Tab");
  assert.ok(evaluate("document.activeElement===document.querySelector('#a11y-run-second-citation-c1 summary')"),
    "Tab from focused evidence must reach that citation's full-excerpt disclosure");
  run("press", "Enter");
  assert.equal(evaluate("document.querySelector('#a11y-run-second-citation-c1 details').open"),true);
  console.log("Per-turn keyboard citation and full-excerpt focus passed");
} finally { run("close"); }
