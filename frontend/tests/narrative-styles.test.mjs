import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
const source=await readFile(new URL('../src/narrative/styleModel.ts',import.meta.url),'utf8');
const {outputText}=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2021}});
const model=await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
const images=Array.from({length:4},(_,i)=>({asset:{id:String(i),status:'approved',media_type:'image/png',sha256:String(i),width:832,height:1216},caption:' navy coat '}));
test('training requires four distinct approved images, reviewed captions and rights',()=>{
 const body=model.styleBody(' Evening ',images,true,200,42,'key');
 assert.equal(body.images.length,4);assert.equal(body.name,'Evening');assert.equal(body.images[0].caption,'navy coat');
 for(const args of [['x',images,false,200,42],['x',images.slice(0,3),true,200,42],['x',[images[0],...images.slice(0,3)],true,200,42],['x',images.map(v=>({...v,caption:''})),true,200,42],['x',images,true,401,42]])assert.throws(()=>model.styleBody(...args,'key'));
});

test('character training requires the reviewed base, same-look and anatomy review',()=>{
 const look={id:'look',sha256:'lookhash',character_id:'mira',source_sha256:'0',asset:images[0].asset};
 const target={look,characterId:'mira',sameLook:true,anatomyReviewed:true};
 assert.equal(model.styleBody('Travel coat',images,true,200,42,'key',target).character_look.look_id,'look');
 for(const invalid of [{...target,sameLook:false},{...target,anatomyReviewed:false},{...target,look:{...look,source_sha256:'missing'}}])assert.throws(()=>model.styleBody('Travel coat',images,true,200,42,'key',invalid));
});
test('pose versions are filtered to this exact character look',()=>{
 const look={id:'a',sha256:'ahash',character_id:'mira'};
 const style={id:'style',status:'completed',kind:'project_style'};
 const own={id:'own',status:'completed',kind:'character_look',look:{id:'a',sha256:'ahash',character_id:'mira'}};
 const wrong={...own,id:'wrong',look:{...own.look,id:'b'}};
 assert.deepEqual(model.compatibleAdapters([style,own,wrong],look).map(j=>j.id),['style','own']);
});

test('training refuses a selected image explicitly flagged for anatomy',()=>{
 assert.throws(()=>model.styleBody('Travel coat',images,true,200,42,'key',undefined,new Set(['0'])),/anatomy/i);
 assert.equal(model.styleBody('Travel coat',images,true,200,42,'key',undefined,new Set(['other'])).images.length,4);
 assert.match(model.styleStatus({status:'failed',error_code:'anatomy_review_failed'}),/anatomy/i);
});

test('a caption proposal changes only the explicitly selected unchanged source',()=>{
 const proposal={asset_id:'1',source_sha256:'1',caption:'white hair, sitting, chair'};
 const next=model.applyCaptionSuggestion(images,proposal);
 assert.equal(next[1].caption,proposal.caption);
 assert.equal(next[0].caption,images[0].caption);
 assert.equal(images[1].caption,' navy coat ');
 for(const invalid of [{...proposal,source_sha256:'changed'},{...proposal,asset_id:'gone'},{...proposal,caption:''},{...proposal,caption:'x'.repeat(601)}]){
  assert.throws(()=>model.applyCaptionSuggestion(images,invalid));
 }
});

test('reference training is explicit and requires a reviewed character target',()=>{
 const look={id:'look',sha256:'lookhash',character_id:'mira',source_sha256:'0',asset:images[0].asset};
 const target={look,characterId:'mira',sameLook:true,anatomyReviewed:true,referenceConditioned:true};
 assert.equal(model.styleBody('Travel coat',images,true,200,42,'key',target).conditioning,'reference');
 assert.equal('conditioning' in model.styleBody('Travel coat',images,true,200,42,'key',{...target,referenceConditioned:false}),false);
});
