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
