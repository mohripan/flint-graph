import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
const source = await readFile(new URL("../src/narrative/poseModel.ts",import.meta.url),"utf8");
const {outputText}=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2021}});
const model=await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
test("a pose request requires an approved locked look and bounded instructions",()=>{
 const look={id:"look",asset:{status:"approved"}};
 assert.deepEqual(model.poseBody(look," sitting   on a chair ",2,true,"key"),{
  look_id:"look",pose:"sitting on a chair",count:2,transparent:true,idempotency_key:"key"});
 for(const args of [[null,"standing",1],[{...look,asset:{status:"candidate"}},"standing",1],
  [look," ",1],[look,"x".repeat(301),1],[look,"standing",5]]){
  assert.throws(()=>model.poseBody(...args,true,"key"));
 }
});
test("pose status names resource shortages and preserves cancellation",()=>{
 assert.match(model.poseStatus({status:"failed",error_code:"host_memory_busy"}),/memory/i);
 assert.equal(model.poseStatus({status:"running",cancel_requested:true}),"Cancelling…");
 assert.equal(model.poseStatus({status:"completed",assets:[{},{}]}),"2 poses ready");
});

test("pose renders do not appear a second time under generated portraits",()=>{
 assert.deepEqual(model.portraitJobs([{id:"ordinary"},{id:"pose"}], [{job:{id:"pose"}}]),[{id:"ordinary"}]);
});

test("an additional approved view requires explicit same-look confirmation",()=>{
 const look={id:"look",source_sha256:"primaryhash",asset:{id:"primary",status:"approved"}};
 const extra={asset:{id:"side",status:"approved",sha256:"sidehash",media_type:"image/png"},view:"side",confirmed:true};
 assert.deepEqual(model.poseBody(look,"standing",1,true,"key",extra).additional_references,[{asset_id:"side",view:"side"}]);
 for(const value of [{...extra,confirmed:false},{...extra,view:"random"},{...extra,asset:{...extra.asset,id:"primary"}},{...extra,asset:{...extra.asset,status:"candidate"}}]){
  assert.throws(()=>model.poseBody(look,"standing",1,true,"key",value));
 }
});

test('poses pin only a completed style version and bounded strength',()=>{
 const look={id:'look',asset:{status:'approved'}};
 const style={id:'version',status:'completed',weights_sha256:'hash'};
 assert.deepEqual(model.poseBody(look,'sitting',1,false,'key',undefined,{style,strength:0.5}).style_adapter,{id:'version',strength:0.5});
 for(const selected of [{style:{...style,status:'running'},strength:0.5},{style,strength:2}])assert.throws(()=>model.poseBody(look,'sitting',1,false,'key',undefined,selected));
});

test('a pose can select this exact trained character look alongside a project style',()=>{
 const look={id:'look',sha256:'lookhash',asset:{status:'approved'}};
 const character={id:'character',kind:'character_look',status:'completed',weights_sha256:'c',look:{id:'look',sha256:'lookhash'}};
 const style={id:'style',kind:'project_style',status:'completed',weights_sha256:'s'};
 const body=model.poseBody(look,'walking',1,false,'key',undefined,{style,strength:0.4},{style:character,strength:0.6});
 assert.deepEqual(body.character_adapter,{id:'character',strength:0.6});
 assert.deepEqual(body.style_adapter,{id:'style',strength:0.4});
 for(const [chosen,identity] of [
  [{style,strength:0.6},{style:character,strength:0.6}],
  [{style:character,strength:0.4},{style:character,strength:0.6}],
  [{style,strength:0.4},{style,strength:0.6}],
  [{style,strength:0.4},{style:{...character,look:{id:'other',sha256:'other'}},strength:0.6}],
 ])assert.throws(()=>model.poseBody(look,'walking',1,false,'key',undefined,chosen,identity));
 assert.equal(model.poseBody(look,'walking',1,false,'key',undefined,undefined,{style:character,strength:0.6}).character_adapter.id,'character');
});


test('an explicit seated guide replaces the extra appearance view without changing legacy bodies',()=>{
 const look={id:'look',asset:{status:'approved'}};
 assert.equal(model.poseBody(look,'sitting',1,false,'key',undefined,undefined,undefined,'seated-front-v1').pose_guide,'seated-front-v1');
 assert.equal('pose_guide' in model.poseBody(look,'sitting',1,false,'key'),false);
 assert.throws(()=>model.poseBody(look,'sitting',1,false,'key',undefined,undefined,undefined,'unknown-guide'));
 const extra={asset:{id:'side',sha256:'other',status:'approved',media_type:'image/png'},view:'side',confirmed:true};
 assert.throws(()=>model.poseBody(look,'sitting',1,false,'key',extra,undefined,undefined,'seated-front-v1'));
});
