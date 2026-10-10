import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";

const baseUrl = new URL(process.env.FLINT_GRAPH_BROWSER_URL ?? "http://127.0.0.1:5173");
assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(baseUrl.hostname));
assert.ok(process.env.npm_execpath, "Use npm run test:conversations");
const session = `flintgraph-conversations-${process.pid}`;
let starting = true;
const run = (...args) => {
  const stdio = starting ? ["ignore", "inherit", "inherit"] : ["ignore", "pipe", "pipe"];
  starting = false;
  return execFileSync(process.execPath, [process.env.npm_execpath, "exec", "--yes",
    "--package=agent-browser@0.39.0", "--", "agent-browser", "--session", session, ...args],
  { encoding: "utf8", windowsHide: true, timeout: 60000, stdio });
};
const route = (pattern, body) => run("network", "route", pattern, "--body", JSON.stringify(body));
const evaluate = (script) => JSON.parse(run("eval", "--base64", Buffer.from(script).toString("base64")).trim());
const conversation = { id: "thread-a", tenant_id: "qa-workspace", title: "Prior-year research",
  next_turn_number: 3, archived_at: null, created_at: "2026-10-10T01:00:00Z", updated_at: "2026-10-10T01:00:00Z" };
const turns = [2017, 2016].map((year, index) => ({ id: `turn-${index}`, tenant_id: "qa-workspace",
  conversation_id: "thread-a", turn_number: index+1, run: { id: `run-${index}`, tenant_id: "qa-workspace",
    query_text: index ? "What about the prior year?" : "What was revenue in 2017?", status: "completed",
    answer_text: `${year} source-backed synthetic answer. [c1]`, answer_citations: [{citation_id:"c1"}],
    query_diagnostics: {support_status_counts:{supported:1}}, created_at: conversation.created_at,
    metadata: {conversation_context:{mode:index ? "resolved" : "independent", resolved_query:index ? "What was revenue in 2016?" : null}} } }));

try {
  route("**/v1/workspaces", [{ id: "qa-workspace", name: "Conversation browser QA", role: "owner" },
    {id:"qa-other",name:"Other browser QA",role:"owner"},{id:"qa-viewer",name:"Read-only browser QA",role:"viewer"}]);
  route("**/health/ready", {status:"ok"});
  route("**/v1/system-readiness**", {setup_capabilities:{conversation_ledger:true,conversation_discovery:true,prior_year_followups:true,chained_conversations:false}});
  route("**/v1/search-readiness**", {ready:true,reason:"searchable",completed_coverage_count:1,documents:[]});
  route("**/v1/conversations", [conversation]);
  route("**/v1/conversations?**", [conversation]);
  route("**/v1/conversations/thread-a", conversation);
  route("**/v1/conversations/thread-a/turns**", turns);
  run("open", baseUrl.href);
  run("wait", "--fn", "document.querySelector('textarea') !== null");
  assert.ok(evaluate("!!document.querySelector('[aria-label=\"Conversation transcript\"]')"), "Delivered capabilities must enable a transcript, not the single-question form");
  evaluate("window.qaWrites=0;const original=window.fetch;window.fetch=(url,init)=>{if(init?.method&&init.method!=='GET')window.qaWrites++;return original(url,init)};true");
  run("find", "role", "button", "click", "--name", "Prior-year research", "--exact");
  run("wait", "--fn", "document.body.textContent.includes('2016 source-backed synthetic answer.')");
  assert.ok(evaluate("document.body.textContent.includes('2017 source-backed synthetic answer.')"));
  assert.equal(evaluate("window.qaWrites"), 0, "Reopening a thread must not start inference");
  assert.ok(evaluate("document.body.textContent.includes('What was revenue in 2016?')"));
  for (const width of [390,1280]) {
    run("set", "viewport", String(width), "900");
    const bounds=evaluate(`(()=>{const input=document.querySelector('textarea').getBoundingClientRect();return{width:innerWidth,scrollWidth:document.documentElement.scrollWidth,input:{top:input.top,bottom:input.bottom,left:input.left,right:input.right}}})()`);
    assert.ok(bounds.scrollWidth <= width+1, `No horizontal overflow at ${width}px`);
    assert.ok(bounds.input.bottom <= 900 && bounds.input.left>=0 && bounds.input.right<=width+1, "Composer remains visible");
  }
  console.log("Read-only ordered conversation and responsive composer checks passed");
  // Focused discovery cycles keep the full default regression unchanged.
  if (!process.argv.includes("--discovery-only") && !process.argv.includes("--recovery-only") && !process.argv.includes("--scroll-only")) {
  evaluate(`(() => {
    const original=window.fetch;
    window.fetch=async(input,init)=>{
      const url=new URL(input,location.origin);
      if(url.pathname.endsWith('/provenance')) {
        const runId=url.pathname.split('/')[3];
        return new Response(JSON.stringify({query_run_id:runId,answer_text:null,abstained:false,
          supported_claim_count:1,unsupported_claim_count:0,answer_provider:'test',
          citations:[{citation_id:'c1',context_id:'context-'+runId,text:'Exact source for '+runId,
            source_ids:{document_id:'document-'+runId},metadata:{title:'Report '+runId},claims:[{support_status:'supported'}]}]}),
          {status:200,headers:{'Content-Type':'application/json'}});
      } return original(input,init);
    };return true;
  })()`);
  assert.ok(evaluate("!!document.querySelector('[aria-label=\"Sources for turn 1\"]')"), "Every answer needs its own source inspection control");
  run("click", "[aria-label='Sources for turn 1']");
  run("wait", "--fn", "document.body.textContent.includes('Exact source for run-0')");
  evaluate("document.querySelector('[aria-label=\"Sources for turn 2\"]').scrollIntoView({block:'center'});true");
  run("click", "[aria-label='Sources for turn 2']");
  run("wait", "--fn", "document.body.textContent.includes('Exact source for run-1')");
  const sourceIds=evaluate("[...document.querySelectorAll('[id$=\"citation-c1\"]')].map(item=>item.id)");
  assert.equal(sourceIds.length,2);
  assert.equal(new Set(sourceIds).size,2,"Repeated c1 labels must have different turn-scoped DOM identities");
  console.log("Per-turn source inspection keeps repeated citation labels isolated");
  run("set", "viewport", "1280", "900");
  evaluate(`(() => {
    const original=window.fetch;
    window.qaTurnPosts=[];
    window.qaTurns=${JSON.stringify(turns)};
    const complete={...window.qaTurns[1].run,id:'run-next',query_text:'What about the prior year?',
      answer_text:'2015 fresh synthetic answer. [c1]',metadata:{conversation_context:{mode:'resolved',resolved_query:'What was revenue in 2015?'}}};
    const json=body=>new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}});
    window.fetch=async(input,init)=>{
      const url=new URL(input,location.origin);
      if(url.pathname==='/v1/conversations/thread-a/turns'&&init?.method==='POST'){
        window.qaTurnPosts.push(JSON.parse(init.body));
        const turn={id:'turn-next',tenant_id:'qa-workspace',conversation_id:'thread-a',turn_number:3,run:{...complete,status:'queued',answer_text:null}};
        window.qaTurns.push({...turn,run:complete});
        return json(turn);
      }
      if(url.pathname==='/v1/query-runs/run-next/events/stream') return new Response('data: '+JSON.stringify({event_type:'query.completed',payload:{}})+'\\n\\n',{headers:{'Content-Type':'text/event-stream'}});
      if(url.pathname==='/v1/query-runs/run-next') return json(complete);
      if(url.pathname==='/v1/conversations/thread-a/turns') return json(window.qaTurns);
      if(url.pathname==='/v1/conversations/thread-a') return json({...${JSON.stringify(conversation)},next_turn_number:4});
      return original(input,init);
    };return true;
  })()`);
  run("find", "label", "Your question", "fill", "What about the prior year?");
  assert.ok(evaluate("[...document.querySelectorAll('button')].some(button=>button.textContent.trim()==='Send')"), "A member needs an explicit Send action");
  run("find", "role", "button", "click", "--name", "Send", "--exact");
  run("wait", "--fn", "document.body.textContent.includes('2015 fresh synthetic answer.')");
  assert.ok(evaluate("document.body.textContent.includes('2017 source-backed synthetic answer.')&&document.body.textContent.includes('2016 source-backed synthetic answer.')"));
  const submission=evaluate("window.qaTurnPosts");
  assert.equal(submission.length,1);
  assert.equal(submission[0].query,"What about the prior year?");
  assert.match(submission[0].idempotency_key,/^[a-f0-9-]{36}$/);
  assert.deepEqual(Object.keys(submission[0]).sort(),["idempotency_key","query","stream"]);
  console.log("Fresh turn submission preserves the original transcript and server identity");
  evaluate(`(() => {
    const original=window.fetch;
    window.qaRetryPosts=[];
    const complete={...window.qaTurns[1].run,id:'run-retry',query_text:'What were margins in 2015?',answer_text:'Recovered synthetic answer. [c1]'};
    const turn={id:'turn-retry',tenant_id:'qa-workspace',conversation_id:'thread-a',turn_number:4,run:{...complete,status:'queued',answer_text:null}};
    const json=body=>new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}});
    window.fetch=async(input,init)=>{
      const url=new URL(input,location.origin);
      if(url.pathname==='/v1/conversations/thread-a/turns'&&init?.method==='POST'){
        window.qaRetryPosts.push(JSON.parse(init.body));
        if(window.qaRetryPosts.length===1){window.qaTurns.push({...turn,run:complete});throw new TypeError('Synthetic response loss');}
        return json(turn);
      }
      if(url.pathname==='/v1/query-runs/run-retry/events/stream') return new Response('data: '+JSON.stringify({event_type:'query.completed',payload:{}})+'\\n\\n',{headers:{'Content-Type':'text/event-stream'}});
      if(url.pathname==='/v1/query-runs/run-retry') return json(complete);
      return original(input,init);
    };return true;
  })()`);
  run("find", "label", "Your question", "fill", "What were margins in 2015?");
  run("find", "role", "button", "click", "--name", "Send", "--exact");
  run("wait", "--fn", "document.body.textContent.includes('Retry sending safely')");
  run("find", "role", "button", "click", "--name", "Retry sending safely", "--exact");
  run("wait", "--fn", "document.body.textContent.includes('Recovered synthetic answer.')");
  const retries=evaluate("window.qaRetryPosts");
  assert.equal(retries.length,2);
  assert.equal(retries[0].idempotency_key,retries[1].idempotency_key);
  assert.equal(evaluate("document.querySelectorAll('[aria-label=\"Turn 4\"]').length"),1);
  console.log("Lost-response retry reuses one request identity and one turn");
  assert.ok(evaluate("[...document.querySelectorAll('button')].some(button=>button.textContent.trim()==='New chat')"), "New chat must start an isolated transcript");
  run("find", "role", "button", "click", "--name", "New chat", "--exact");
  assert.ok(evaluate("document.querySelectorAll('[aria-label^=\"Turn \"]').length===0&&!document.body.textContent.includes('Recovered synthetic answer.')"), "New chat cannot inherit earlier messages");
  assert.equal(evaluate("document.querySelector('textarea').value"), "");
  console.log("New chat clears the visible transcript without deleting saved history");
  }
  if (!process.argv.includes("--recovery-only") && !process.argv.includes("--scroll-only")) {
  assert.ok(evaluate("!!document.querySelector('[aria-label=\"Search conversations\"]')"), "Conversation discovery needs a title search");
  evaluate(`(() => {
    const original=window.fetch;window.qaDiscoveryRequests=[];
    window.fetch=async(input,init)=>{
      const url=new URL(input,location.origin);
      if(url.pathname==='/v1/conversations'&&(!init?.method||init.method==='GET')){
        window.qaDiscoveryRequests.push(url.search);
        const query=url.searchParams.get('q');
        return new Response(JSON.stringify(query==='missing title'?[]:[${JSON.stringify(conversation)}]),{headers:{'Content-Type':'application/json'}});
      } return original(input,init);
    };return true;
  })()`);
  run("find","label","Search conversations","fill","missing title");
  run("wait","--fn","document.body.textContent.includes('No matching conversations.')");
  assert.ok(evaluate("window.qaDiscoveryRequests.some(value=>new URLSearchParams(value).get('q')==='missing title')"));
  run("find","label","Search conversations","click");
  run("press","Control+a");
  run("press","Backspace");
  run("wait","--fn","[...document.querySelectorAll('button')].some(button=>button.textContent.trim()==='Prior-year research')");
  run("find","role","button","click","--name","Prior-year research","--exact");
  run("wait","--fn","document.body.textContent.includes('2017 source-backed synthetic answer.')");
  console.log("Title search uses the authorized server list, with an explicit empty result");
  assert.ok(evaluate("[...document.querySelectorAll('button')].some(button=>button.textContent.trim()==='Rename')"), "Members need an explicit rename action");
  evaluate(`(() => {
    const original=window.fetch;window.qaRenamePosts=[];
    window.fetch=async(input,init)=>{
      const url=new URL(input,location.origin);
      if(url.pathname==='/v1/conversations/thread-a'&&init?.method==='PATCH'){
        window.qaRenamePosts.push(JSON.parse(init.body));
        return new Response(JSON.stringify({...${JSON.stringify(conversation)},title:'Renamed research'}),{headers:{'Content-Type':'application/json'}});
      }return original(input,init);
    };return true;
  })()`);
  run("wait","--fn","[...document.querySelectorAll('button')].some(button=>button.textContent.trim()==='Rename'&&!button.disabled)");
  run("find","role","button","click","--name","Rename","--exact");
  run("wait","--fn","!!document.querySelector('input[maxlength=\"200\"]:not([aria-label])')");
  run("find","label","Conversation title","fill","Renamed research");
  run("find","role","button","click","--name","Save title","--exact");
  run("wait","--fn","document.querySelector('h1').textContent==='Renamed research'");
  assert.deepEqual(evaluate("window.qaRenamePosts"),[{title:"Renamed research"}]);
  console.log("Member rename changes only the shared conversation title");
  evaluate(`(() => {
    const original=window.fetch;window.qaPageRequests=[];
    window.fetch=async(input,init)=>{
      const url=new URL(input,location.origin);
      if(url.pathname==='/v1/conversations'&&url.searchParams.get('q')==='paged'){
        window.qaPageRequests.push(url.search);
        const rows=url.searchParams.has('before_id')?[{...${JSON.stringify(conversation)},id:'older-thread',title:'Older research'}]:
          Array.from({length:25},(_,index)=>({...${JSON.stringify(conversation)},id:'page-'+index,title:'Paged research '+index}));
        return new Response(JSON.stringify(rows),{headers:{'Content-Type':'application/json'}});
      }return original(input,init);
    };return true;
  })()`);
  run("find","label","Search conversations","fill","paged");
  run("wait","--fn","document.body.textContent.includes('Paged research 24')");
  assert.ok(evaluate("[...document.querySelectorAll('button')].some(button=>button.textContent.trim()==='Load older conversations')"), "Conversation history must not truncate silently after one page");
  evaluate("[...document.querySelectorAll('button')].find(button=>button.textContent.trim()==='Load older conversations').scrollIntoView({block:'center'});true");
  run("find","role","button","click","--name","Load older conversations","--exact");
  run("wait","--fn","document.body.textContent.includes('Older research')");
  assert.ok(evaluate("document.body.textContent.includes('Paged research 0')"));
  assert.equal(evaluate("new URLSearchParams(window.qaPageRequests.at(-1)).get('before_id')"),"page-24");
  console.log("Conversation pagination keeps earlier rows and uses the authorized server cursor");
  evaluate(`(() => {
    const original=window.fetch;window.qaTurnPageRequests=[];
    window.fetch=async(input,init)=>{
      const url=new URL(input,location.origin);const json=value=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});
      if(url.pathname==='/v1/conversations/thread-a'&&(!init?.method||init.method==='GET')) return json({...${JSON.stringify(conversation)},next_turn_number:4});
      if(url.pathname==='/v1/conversations/thread-a/turns'&&(!init?.method||init.method==='GET')){
        window.qaTurnPageRequests.push(url.search);
        return json(url.searchParams.has('after_id')?[{...${JSON.stringify(turns[1])},id:'page-turn-3',turn_number:3,
          run:{...${JSON.stringify(turns[1].run)},id:'page-run-3',answer_text:'Last paged answer.'}}]:${JSON.stringify(turns)});
      }return original(input,init);
    };return true;
  })()`);
  run("find","label","Search conversations","fill","turns");
  run("wait","--fn","[...document.querySelectorAll('button')].some(button=>button.textContent.trim()==='Prior-year research')");
  run("find","role","button","click","--name","Prior-year research","--exact");
  run("wait","--fn","document.body.textContent.includes('Load the remaining turns before following up.')");
  assert.ok(evaluate("[...document.querySelectorAll('button')].some(button=>button.textContent.trim()==='Load remaining turns')"), "A paged thread needs a reachable next-turn action");
  run("find","role","button","click","--name","Load remaining turns","--exact");
  run("wait","--fn","document.body.textContent.includes('Last paged answer.')");
  assert.equal(evaluate("document.querySelectorAll('[aria-label^=\"Turn \"]').length"),3);
  assert.equal(evaluate("new URLSearchParams(window.qaTurnPageRequests.at(-1)).get('after_id')"),"turn-1");
  console.log("Turn pagination preserves order and gates follow-ups until the latest turn is loaded");
  run("reload");
  run("wait","--fn","!!document.querySelector('textarea')&&![...document.querySelectorAll('[role=status]')].some(item=>item.textContent.includes('Loading history')||item.textContent.includes('Opening conversation'))");
  assert.equal(evaluate("document.querySelector('h1').textContent"),"Prior-year research","Reload must reopen the selected server conversation, not discard it");
  run("wait","--fn","document.body.textContent.includes('2016 source-backed synthetic answer.')");
  assert.equal(evaluate("document.querySelectorAll('[aria-label^=\"Turn \"]').length"),2,"Server state replaces previous browser-only fixture content");
  assert.ok(evaluate("!performance.getEntriesByType('resource').some(item=>item.name.includes('/events/stream'))"),"Reload is read-only, not inference replay");
  console.log("Reload restores only conversation identity and reopens authoritative server turns without inference");
  }
  if (!process.argv.includes("--scroll-only")) {
  assert.ok(evaluate("[...document.querySelectorAll('button')].some(button=>button.textContent.trim()==='Refresh conversation')"),"Persisted incomplete turns need a read-only refresh action");
  evaluate(`(() => {
    const original=window.fetch;window.qaRecoveryStreams=0;window.qaRecoveryCreates=0;
    window.qaRecoveryRun={...${JSON.stringify(turns[1].run)},id:'queued-run',status:'queued',query_text:'Queued synthetic question',answer_text:null};
    window.fetch=async(input,init)=>{
      const url=new URL(input,location.origin);const json=value=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});
      if(url.pathname==='/v1/conversations/thread-a') return json({...${JSON.stringify(conversation)},next_turn_number:4});
      if(url.pathname==='/v1/conversations/thread-a/turns'){
        if(init?.method==='POST')window.qaRecoveryCreates++;
        return json([...${JSON.stringify(turns)},{...${JSON.stringify(turns[1])},id:'queued-turn',turn_number:3,run:window.qaRecoveryRun}]);
      }
      if(url.pathname==='/v1/query-runs/queued-run/events/stream'){
        window.qaRecoveryStreams++;window.qaRecoveryRun={...window.qaRecoveryRun,status:'completed',answer_text:'Recovered queued turn.'};
        return new Response('data: '+JSON.stringify({event_type:'query.completed',payload:{}})+'\\n\\n',{headers:{'Content-Type':'text/event-stream'}});
      }
      if(url.pathname==='/v1/query-runs/queued-run')return json(window.qaRecoveryRun);
      return original(input,init);
    };return true;
  })()`);
  run("find","role","button","click","--name","Refresh conversation","--exact");
  run("wait","--fn","!!document.querySelector('[aria-label=\"Turn 3\"]')");
  assert.equal(evaluate("window.qaRecoveryStreams"),0,"Read-only refresh cannot execute a queued turn");
  run("find","role","button","click","--name","Resume queued turn","--exact");
  run("wait","--fn","document.body.textContent.includes('Recovered queued turn.')");
  assert.equal(evaluate("window.qaRecoveryStreams"),1);
  assert.equal(evaluate("window.qaRecoveryCreates"),0,"Resume must use the existing run identity, not create another turn");
  console.log("Queued recovery is explicit and resumes the existing run without duplicate submission");
  evaluate(`(() => {
    const original=window.fetch;window.qaQueuedCancels=[];
    window.qaCancelRun={...${JSON.stringify(turns[1].run)},id:'cancel-run',status:'queued',query_text:'Cancel queued synthetic question',answer_text:null};
    window.fetch=async(input,init)=>{
      const url=new URL(input,location.origin);const json=value=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});
      const turn={...${JSON.stringify(turns[1])},id:'cancel-turn',turn_number:4,run:window.qaCancelRun};
      if(url.pathname==='/v1/conversations/thread-a/turns/cancel-turn/cancel'){
        window.qaQueuedCancels.push({path:url.pathname,method:init?.method});
        window.qaCancelRun={...window.qaCancelRun,status:'cancelled'};return json({...turn,run:window.qaCancelRun});
      }
      if(url.pathname==='/v1/conversations/thread-a')return json({...${JSON.stringify(conversation)},next_turn_number:5});
      if(url.pathname==='/v1/conversations/thread-a/turns')return json([...${JSON.stringify(turns)},
        {...${JSON.stringify(turns[1])},id:'queued-turn',turn_number:3,run:window.qaRecoveryRun},turn]);
      return original(input,init);
    };return true;
  })()`);
  run("find","role","button","click","--name","Refresh conversation","--exact");
  run("wait","--fn","!!document.querySelector('[aria-label=\"Turn 4\"]')");
  assert.ok(evaluate("[...document.querySelectorAll('button')].some(button=>button.textContent.trim()==='Cancel queued turn')"),"A member needs queued-only cancellation without starting inference");
  run("set","viewport","390","900");
  assert.ok(evaluate("document.documentElement.scrollWidth<=innerWidth+1"),"Queued recovery controls must fit a mobile viewport");
  run("find","role","button","click","--name","Cancel queued turn","--exact");
  run("wait","--fn","document.querySelector('[aria-label=\"Turn 4\"]').textContent.includes('cancelled')");
  assert.deepEqual(evaluate("window.qaQueuedCancels"),[{path:"/v1/conversations/thread-a/turns/cancel-turn/cancel",method:"POST"}]);
  assert.equal(evaluate("window.qaRecoveryStreams"),1,"Queued cancellation does not start another stream");
  console.log("Queued cancellation uses the dedicated server endpoint, without inference");
  run("set","viewport","1280","900");
  evaluate(`(() => {
    const original=window.fetch;window.qaStopped=false;window.qaStopStreams=0;
    window.qaStopRun={...${JSON.stringify(turns[1].run)},id:'stop-run',status:'queued',query_text:'Stop active synthetic question',answer_text:null};
    window.fetch=async(input,init)=>{
      const url=new URL(input,location.origin);const json=value=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});
      if(url.pathname==='/v1/conversations/thread-a')return json({...${JSON.stringify(conversation)},next_turn_number:6});
      if(url.pathname==='/v1/conversations/thread-a/turns')return json([...${JSON.stringify(turns)},
        {...${JSON.stringify(turns[1])},id:'queued-turn',turn_number:3,run:window.qaRecoveryRun},
        {...${JSON.stringify(turns[1])},id:'cancel-turn',turn_number:4,run:window.qaCancelRun},
        {...${JSON.stringify(turns[1])},id:'stop-turn',turn_number:5,run:window.qaStopped?{...window.qaStopRun,status:'cancelled'}:window.qaStopRun}]);
      if(url.pathname==='/v1/query-runs/stop-run')return json(window.qaStopped?{...window.qaStopRun,status:'cancelled'}:window.qaStopRun);
      if(url.pathname==='/v1/query-runs/stop-run/events/stream'){
        window.qaStopStreams++;window.qaStopRun={...window.qaStopRun,status:'running'};
        return new Response(new ReadableStream({start(controller){
          controller.enqueue(new TextEncoder().encode('data: '+JSON.stringify({event_type:'query.started',payload:{}})+'\\n\\n'+
            'data: '+JSON.stringify({event_type:'query.answer_delta',payload:{delta:'UNVERIFIED_DRAFT_SENTINEL'}})+'\\n\\n'));
          init.signal.addEventListener('abort',()=>{window.qaStopped=true;controller.error(new DOMException('Stopped','AbortError'));},{once:true});
        }}),{headers:{'Content-Type':'text/event-stream'}});
      }return original(input,init);
    };return true;
  })()`);
  run("find","role","button","click","--name","Refresh conversation","--exact");
  run("wait","--fn","!!document.querySelector('[aria-label=\"Turn 5\"]')");
  run("find","role","button","click","--name","Resume queued turn","--exact");
  run("wait","--fn","document.querySelector('[aria-label=\"Turn 5\"]').textContent.includes('running')");
  assert.ok(evaluate("!document.body.textContent.includes('UNVERIFIED_DRAFT_SENTINEL')"),"Draft stream output is not a trusted final answer");
  assert.ok(evaluate("[...document.querySelectorAll('button')].some(button=>button.textContent.trim()==='Stop stream')"),"An active request-bound stream needs an explicit Stop action");
  run("find","role","button","click","--name","Stop stream","--exact");
  run("wait","--fn","document.body.textContent.includes('Stream stopped locally')");
  assert.ok(evaluate("document.querySelector('[aria-label=\"Turn 5\"]').textContent.includes('running')"),"Local stop does not invent a terminal backend state");
  run("find","role","button","click","--name","Refresh conversation","--exact");
  run("wait","--fn","document.querySelector('[aria-label=\"Turn 5\"]').textContent.includes('cancelled')");
  assert.equal(evaluate("window.qaStopStreams"),1);
  assert.equal(evaluate("window.qaQueuedCancels.length"),1,"Stopping a running stream is not queued cancellation");
  console.log("Request-bound stop hides drafts and relies on authoritative refresh for terminal state");
  evaluate(`(() => {
    const original=window.fetch;
    window.fetch=async(input,init)=>{
      const url=new URL(input,location.origin);
      if(url.pathname.endsWith('/provenance'))return new Response(JSON.stringify({detail:'Synthetic revoked membership'}),
        {status:403,headers:{'Content-Type':'application/json'}});
      return original(input,init);
    };return true;
  })()`);
  evaluate("document.querySelector('[aria-label=\"Sources for turn 1\"]').scrollIntoView({block:'center'});true");
  run("click","[aria-label='Sources for turn 1']");
  run("wait","--fn","document.body.textContent.includes('Workspace access was denied')");
  assert.ok(evaluate("!document.querySelector('textarea')&&!document.querySelector('[aria-label=\"Conversations\"]')&&!document.querySelector('[aria-label^=\"Turn \"]')"),"Revoked access must clear messages, composer and sidebar, not just display an error");
  console.log("Denied source access clears the whole conversation view and removes further actions");
  evaluate(`(() => {
    const original=window.fetch;window.qaViewerWrites=0;
    const template=${JSON.stringify(conversation)};const message=${JSON.stringify(turns[0])};
    const slow={...template,id:'slow-thread',tenant_id:'qa-other',title:'Slow conversation',next_turn_number:2};
    const fast={...slow,id:'fast-thread',title:'Fast conversation'};
    const viewer={...slow,id:'viewer-thread',tenant_id:'qa-viewer',title:'Viewer conversation',next_turn_number:3};
    const json=value=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});
    const turn=(row,text)=>({...message,id:row.id+'-turn',tenant_id:row.tenant_id,conversation_id:row.id,
      run:{...message.run,id:row.id+'-run',tenant_id:row.tenant_id,query_text:'Synthetic isolated question',answer_text:text,
        metadata:{conversation_context:{mode:'independent',resolved_query:null}}}});
    window.fetch=async(input,init)=>{
      const url=new URL(input,location.origin);const tenant=new Headers(init?.headers).get('X-Tenant-ID');
      if(tenant==='qa-viewer'&&init?.method&&init.method!=='GET')window.qaViewerWrites++;
      if(url.pathname==='/v1/conversations'&&tenant==='qa-other')return json([slow,fast]);
      if(url.pathname==='/v1/conversations'&&tenant==='qa-viewer')return json([viewer]);
      if(url.pathname==='/v1/conversations/slow-thread')return new Promise(resolve=>setTimeout(()=>resolve(json(slow)),2500));
      if(url.pathname==='/v1/conversations/slow-thread/turns')return new Promise(resolve=>setTimeout(()=>resolve(json([turn(slow,'STALE_CHAT_SENTINEL')])),2500));
      if(url.pathname==='/v1/conversations/fast-thread')return json(fast);
      if(url.pathname==='/v1/conversations/fast-thread/turns')return json([turn(fast,'FAST_SAFE_ANSWER <img src=x onerror=window.qaInjected=true> [javascript:alert(1)] [c1]')]);
      if(url.pathname==='/v1/conversations/viewer-thread')return json(viewer);
      if(url.pathname==='/v1/conversations/viewer-thread/turns')return json([turn(viewer,'READ_ONLY_ANSWER'),
        {...turn(viewer,null),id:'viewer-queued-turn',turn_number:2,run:{...message.run,id:'viewer-queued-run',status:'queued',answer_text:null}}]);
      if(url.pathname==='/v1/query-runs/fast-thread-run/provenance')return new Promise(resolve=>setTimeout(()=>resolve(json({
        query_run_id:'fast-thread-run',supported_claim_count:1,unsupported_claim_count:0,citations:[{citation_id:'c1',context_id:'late',
          text:'LATE_OLD_SOURCE_SENTINEL',metadata:{title:'Synthetic old source'},source_ids:{},claims:[]}]})),6000));
      return original(input,init);
    };return true;
  })()`);
  run("select","select[aria-label='Workspace']","qa-other");
  run("wait","--fn","[...document.querySelectorAll('button')].some(button=>button.textContent.trim()==='Slow conversation')");
  run("find","role","button","click","--name","Slow conversation","--exact");
  run("find","role","button","click","--name","Fast conversation","--exact");
  run("wait","--fn","document.body.textContent.includes('FAST_SAFE_ANSWER')");
  run("wait","3000");
  assert.ok(evaluate("!document.body.textContent.includes('STALE_CHAT_SENTINEL')"),"A delayed superseded chat cannot restore old messages");
  assert.ok(evaluate("!window.qaInjected&&!document.querySelector('img[src=x]')&&!document.querySelector('a[href^=\"javascript:\"]')"),"Model output remains text, not executable HTML or unsafe links");
  run("click","[aria-label='Sources for turn 1']");
  run("wait","--fn","document.body.textContent.includes('Loading authorized sources')");
  run("select","select[aria-label='Workspace']","qa-viewer");
  run("wait","--fn","[...document.querySelectorAll('button')].some(button=>button.textContent.trim()==='Viewer conversation')");
  run("find","role","button","click","--name","Viewer conversation","--exact");
  run("wait","--fn","document.body.textContent.includes('READ_ONLY_ANSWER')");
  run("wait","6500");
  assert.ok(evaluate("!document.body.textContent.includes('FAST_SAFE_ANSWER')&&!document.body.textContent.includes('LATE_OLD_SOURCE_SENTINEL')"),"Late evidence from the prior workspace cannot enter the new transcript");
  assert.ok(evaluate("document.querySelector('textarea').readOnly&&![...document.querySelectorAll('button')].some(button=>!button.disabled&&['Send','Rename','Resume queued turn','Cancel queued turn','New chat'].includes(button.textContent.trim()))"),"Viewer access reads existing conversations without write/execution actions");
  run("find","label","Your question","click");
  run("press","Control+Enter");
  assert.equal(evaluate("window.qaViewerWrites"),0);
  console.log("Stale chat/source responses, text safety and read-only viewer access remain isolated");
  }
  evaluate(`(() => {
    const original=window.fetch;window.qaLongAppend=0;
    const initial=${JSON.stringify(turns)};
    const long=Array.from({length:80},(_,index)=>'Synthetic long research paragraph '+index+' [c1].').join('\\n\\n')+'\\n'+'W'.repeat(1000);
    window.fetch=async(input,init)=>{
      const url=new URL(input,location.origin);const json=value=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});
      if(url.pathname==='/v1/conversations/thread-a')return json({...${JSON.stringify(conversation)},title:'Long research '+'x'.repeat(180),next_turn_number:3+window.qaLongAppend});
      if(url.pathname==='/v1/conversations/thread-a/turns')return json([
        {...initial[0],run:{...initial[0].run,answer_text:long}},
        {...initial[1],run:{...initial[1].run,answer_text:'SCROLL_BASE_LAST [c1]'}},
        ...Array.from({length:window.qaLongAppend},(_,index)=>({...initial[1],id:'scroll-turn-'+index,turn_number:3+index,
          run:{...initial[1].run,id:'scroll-run-'+index,answer_text:'SCROLL_ADDED_'+(index+1)}}))]);
      return original(input,init);
    };return true;
  })()`);
  run("select","select[aria-label='Workspace']","qa-workspace");
  run("wait","--fn","[...document.querySelectorAll('button')].some(button=>button.textContent.trim()==='Prior-year research')");
  run("find","role","button","click","--name","Prior-year research","--exact");
  run("wait","--fn","document.body.textContent.includes('SCROLL_BASE_LAST')");
  assert.ok(evaluate("(()=>{const el=document.querySelector('[aria-label=\"Conversation transcript\"]');return el.scrollHeight>el.clientHeight&&el.scrollHeight-el.clientHeight-el.scrollTop<4})()"),"Reopening a long thread must reach the latest answer in the primary scroller");
  evaluate("document.querySelector('[aria-label=\"Conversation transcript\"]').scrollTop=0;window.qaLongAppend=1;true");
  run("find","role","button","click","--name","Refresh conversation","--exact");
  run("wait","--fn","document.body.textContent.includes('SCROLL_ADDED_1')");
  assert.ok(evaluate("document.querySelector('[aria-label=\"Conversation transcript\"]').scrollTop<50"),"New content cannot yank someone reading older messages");
  run("find","role","button","click","--name","Jump to latest","--exact");
  run("wait","--fn","(()=>{const el=document.querySelector('[aria-label=\"Conversation transcript\"]');return el.scrollHeight-el.clientHeight-el.scrollTop<4})()");
  evaluate("window.qaLongAppend=2;true");
  run("find","role","button","click","--name","Refresh conversation","--exact");
  run("wait","--fn","document.body.textContent.includes('SCROLL_ADDED_2')");
  assert.ok(evaluate("(()=>{const el=document.querySelector('[aria-label=\"Conversation transcript\"]');return el.scrollHeight-el.clientHeight-el.scrollTop<4})()"),"A reader at the bottom follows newly completed content");
  for(const width of [390,1280]){
    run("set","viewport",String(width),"900");
    assert.ok(evaluate("document.documentElement.scrollWidth<=innerWidth+1&&document.querySelector('textarea').getBoundingClientRect().bottom<=innerHeight"),"Long titles and unbroken answer text keep the composer visible without horizontal overflow");
    assert.ok(evaluate("[...document.querySelectorAll('button')].find(button=>button.textContent.trim()==='New chat').getBoundingClientRect().height<=44"),"New chat must stay on one line beside a long mobile title");
  }
  console.log("Long transcripts use one primary scroller, bottom-aware following and Jump to latest");
  evaluate(`(() => {
    const original=window.fetch;window.fetch=async(input,init)=>{
      const url=new URL(input,location.origin);
      if(url.pathname==='/v1/query-runs/run-1/provenance')return new Response(JSON.stringify({query_run_id:'run-1',
        supported_claim_count:1,unsupported_claim_count:0,citations:[{citation_id:'c1',context_id:'long-source',
          text:Array.from({length:70},(_,index)=>'Synthetic exact source line '+index).join('\\n')+'\\nLAST_EXACT_SOURCE_LINE',
          metadata:{title:'Synthetic full excerpt'},source_ids:{},claims:[{support_status:'supported'}]}]}),{headers:{'Content-Type':'application/json'}});
      return original(input,init);
    };document.querySelector('[aria-label="Sources for turn 2"]').scrollIntoView({block:'center'});return true;
  })()`);
  run("click","[aria-label='Sources for turn 2']");
  run("wait","--fn","document.body.textContent.includes('Synthetic full excerpt')");
  assert.ok(evaluate("!![...document.querySelectorAll('#run-1-citation-c1 summary')].find(item=>item.textContent==='Read full excerpt')"),"Source inspection needs a full excerpt, not just a four-line preview");
  run("click","#run-1-citation-c1 summary");
  const fullQuote=evaluate("(()=>{const details=document.querySelector('#run-1-citation-c1 details');const p=details.querySelector('p');return{open:details.open,full:p.textContent.endsWith('LAST_EXACT_SOURCE_LINE'),height:p.clientHeight,scrollHeight:p.scrollHeight}})()");
  assert.ok(fullQuote.open&&fullQuote.full&&fullQuote.height===fullQuote.scrollHeight,"Full evidence flows in the transcript, not another small internal scroller");
  evaluate("document.querySelector('#run-1-citation-c1 details p').scrollIntoView({block:'end'});true");
  assert.ok(evaluate("document.querySelector('#run-1-citation-c1 details p').getBoundingClientRect().bottom<=document.querySelector('[aria-label=\"Conversation transcript\"]').getBoundingClientRect().bottom+1"));
  console.log("Full source excerpts remain reachable in the same primary transcript scroller");
} finally { run("close"); }
