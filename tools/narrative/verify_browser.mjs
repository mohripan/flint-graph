import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdirSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {parseArgs} from 'node:util';

const {values}=parseArgs({options:{
  'browser-cli':{type:'string'},session:{type:'string'},url:{type:'string'},
  'long-url':{type:'string'},output:{type:'string'}
}});
for(const key of ['browser-cli','session','url','long-url','output']) {
  if(!values[key]) throw new Error('Missing --'+key);
}
for(const key of ['url','long-url']) {
  const target=new URL(values[key]);
  if(target.protocol!=='http:' || !['127.0.0.1','localhost'].includes(target.hostname)) {
    throw new Error('Qualification requires an owned loopback HTTP preview');
  }
}
const qaURL=value=>{const target=new URL(value);target.searchParams.set('qa','1');return target.href;};

const binary=resolve(values['browser-cli']);
const session=values.session;
const url=qaURL(values.url);
const longURL=qaURL(values['long-url']);
const output=resolve(values.output);
mkdirSync(output);
const events=[];
const run=(...args)=>execFileSync(binary,['--session',session,...args],{encoding:'utf8',windowsHide:true,timeout:60000});
const evaluate=source=>JSON.parse(run('eval','--base64',Buffer.from(source).toString('base64')).trim());
const state=()=>evaluate('window.__flintNarrativeQA');
const wait=node=>run('wait','--fn',`window.__flintNarrativeQA?.node_id === ${JSON.stringify(node)}`);
const capture=name=>{run('screenshot',resolve(output,`${name}.png`));events.push({step:name,...state()});};
const click=(x,y)=>{run('mouse','move',String(x),String(y));run('mouse','down','left');run('mouse','up','left');};
try {
  run('set','viewport','1280','900');
  run('open',url);wait('arrival');run('snapshot','-i');
  capture('01-desktop-arrival');
  run('press','Enter');wait('approach_choice');
  capture('02-desktop-choice');
  click(232,117);
  run('wait','--fn','window.__flintNarrativeQA?.has_save === true');
  assert.match(state().notice,/Saved/);
  capture('03-desktop-saved');
  run('press','1');wait('letter_clue');
  run('press','Enter');wait('inquiry');
  run('press','1');wait('promise');
  run('press','Enter');wait('restored_end');
  assert.equal(state().ending,'restored');
  assert.equal(state().view.portrait,null);
  capture('04-desktop-restored-ending');
  // Readiness/persistence is exercised through a real reload and Load click.
  run('open',url);wait('arrival');
  assert.equal(state().has_save,true);
  click(640,117);wait('approach_choice');
  assert.equal(state().view.portrait,null);
  capture('05-desktop-loaded-after-reload');
  run('press','2');wait('quiet_end');
  assert.equal(state().ending,'quiet');
  capture('06-desktop-quiet-ending');
  click(1048,117);wait('arrival');
  run('press','Enter');wait('approach_choice');
  run('press','3');wait('hasty_end');
  assert.equal(state().ending,'hasty');
  capture('07-desktop-hasty-ending');
  run('set','viewport','390','844');
  run('open',url);wait('arrival');
  run('wait','--fn','window.__flintNarrativeQA?.viewport.width === 390');
  capture('08-mobile-arrival');
  run('press','Enter');wait('approach_choice');
  capture('09-mobile-choice');
  for(const control of state().controls) {
    assert.ok([control.x,control.y,control.width,control.height].every(Number.isFinite));
    assert.ok(control.x>=0 && control.y>=0 && control.width>0 && control.height>=44);
    assert.ok(control.x+control.width<=390);
    assert.ok(control.y+control.height<=844);
  }
  run('press','1');wait('letter_clue');
  run('press','Enter');wait('inquiry');
  run('press','1');wait('promise');
  run('press','Enter');wait('restored_end');
  assert.equal(state().ending,'restored');
  capture('10-mobile-restored-ending');
  // Canvas controls are exercised through actual mouse/keyboard input. Read-only
  // QA snapshots report the rendered state; no action bridge or state injection.
  run('open',longURL);wait('arrival');run('snapshot','-i');
  assert.ok(state().view.text.startsWith('Passage 1.'));
  assert.ok(state().controls[0].y>844);
  capture('11-mobile-long-top');
  run('mouse','move','195','650');run('mouse','wheel','22000');
  capture('12-mobile-long-bottom');
  click(195,798);wait('approach_choice');
  capture('13-mobile-long-choice');
  run('set','viewport','1280','900');
  run('open',longURL);wait('arrival');run('snapshot','-i');
  assert.ok(state().controls[0].y>900);
  capture('14-desktop-long-top');
  run('mouse','move','640','650');run('mouse','wheel','22000');
  capture('15-desktop-long-bottom');
  click(640,839);wait('approach_choice');
  capture('16-desktop-long-choice');
  const errors=run('errors');
  assert.equal(errors.trim(),'');
  const consoleLog=run('console');
  assert.doesNotMatch(consoleLog,/\[error\]|SCRIPT ERROR|CONTENT_ERROR/);
  assert.match(consoleLog,/4\.7\.2\.stable\.official\.ed1daf0bf/);
  writeFileSync(resolve(output,'console.log'),consoleLog);
  writeFileSync(resolve(output,'report.json'),JSON.stringify({passed:true,url,longURL,events,errors,consoleErrors:false,browser:run('--version').trim(),note:'Scroll screenshots must also be visually reviewed; QA control rectangles refresh on render/resize, not wheel input.'},null,2)+'\n');
  console.log(JSON.stringify({passed:true,evidence:output,steps:events.length}));
} catch(error) {
  try {run('screenshot',resolve(output,'failure.png'));events.push({step:'failure',...state()});} catch {}
  writeFileSync(resolve(output,'report.json'),JSON.stringify({passed:false,error:String(error),events,console:run('console')},null,2)+'\n');
  console.error('Browser acceptance failed; evidence:',output);
  throw error;
}
// Keep the already-owned session available for visual review; close it when finished.
