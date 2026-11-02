import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
const source=await readFile(new URL('../src/narrative/poseRepairModel.ts',import.meta.url),'utf8');
const {outputText}=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2021}});
const model=await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
test('a repair sends source-native coordinates and accepts unapproved candidates',()=>{
 const asset={id:'source',status:'candidate',media_type:'image/png',width:768,height:1152};
 assert.deepEqual(model.repairBody(asset,[400,500,560,660],' a natural   hand ',2,'key'),{
  asset_id:'source',box:[400,500,560,660],instruction:'a natural hand',count:2,idempotency_key:'key'});
 for(const [box,instruction,count] of [[[0,0,768,1152],'fix',1],[[1,1,10,100],'fix',1],[[1,1,100,100],'',1],[[1,1,100,100],'fix',3]]){
  assert.throws(()=>model.repairBody(asset,box,instruction,count,'key'));
 }
 assert.throws(()=>model.repairBody({...asset,status:'discarded'},[0,0,100,100],'fix',1,'key'));
});
test('repair movement keeps a rectangle inside the native cropped sprite',()=>{
 assert.deepEqual(model.moveRegion([400,500,560,660],500,500,600,900),[440,740,600,900]);
 assert.deepEqual(model.moveRegion([20,30,120,190],-100,-100,600,900),[0,0,100,160]);
 assert.deepEqual(model.resizeRegion([20,30,120,190],-200,-200,600,900),[20,30,36,46]);
 assert.equal(model.validRegion([0,0,300,450],600,900),true);
 assert.equal(model.validRegion([0,0,301,450],600,900),false);
});

test('a small cropped sprite starts with a valid repair region',()=>{
 assert.deepEqual(model.initialRegion(32,32),[10,10,26,26]);
});
