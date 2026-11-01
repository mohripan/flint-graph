import {useEffect,useRef,useState} from 'react';
import {api} from '../lib/api';
import {Field} from './FormFields';
import {LookImage} from './CharacterLooks';
import type {CharacterLook} from './lookModel';
import {lookReferences} from './lookModel';
import {useApprovedAssets} from './libraryAssets';
import {styleBody,styleStatus,trainingAssets} from './styleModel';
import type {StyleHistory,TrainingSelection} from './styleModel';
import './styles.css';

export function useStyleJobs(tenantId:string,projectId:string,enabled=true){
 const [history,setHistory]=useState<StyleHistory|null>(null);
 const [failed,setFailed]=useState(false);
 const [revision,setRevision]=useState(0);
 const active=history?.jobs.some(j=>['queued','running'].includes(j.status))??false;
 useEffect(()=>{
  if(!enabled||!tenantId||!projectId)return;
  const controller=new AbortController();
  const load=()=>api.listStyleJobs(tenantId,projectId,controller.signal).then(value=>{if(!controller.signal.aborted){setHistory(value);setFailed(false);}}).catch(()=>{if(!controller.signal.aborted)setFailed(true);});
  void load();const timer=window.setInterval(()=>void load(),active?1500:10000);
  return ()=>{controller.abort();window.clearInterval(timer);};
 },[tenantId,projectId,enabled,revision,active]);
 return {history,failed,refresh:()=>setRevision(v=>v+1)};
}

export function StyleStudio({tenantId,projectId,readOnly,characterLook,characterId}:{tenantId:string;projectId:string;readOnly:boolean;characterLook?:CharacterLook;characterId?:string}){
 const {history,failed,refresh}=useStyleJobs(tenantId,projectId);
 const library=useApprovedAssets(tenantId,projectId);
 const approved=trainingAssets(library.assets??[]);
 const choices=characterLook?lookReferences(approved,characterId??''):approved;
 const [sameLook,setSameLook]=useState(false);const [anatomy,setAnatomy]=useState(false);
 const suggestedCaption=characterLook?[...characterLook.identity_tags,...characterLook.clothing_tags].join(', '):'';
 const [selected,setSelected]=useState<TrainingSelection[]>([]);
 const [name,setName]=useState('');const [rights,setRights]=useState(false);
 useEffect(()=>{
  setSelected(characterLook&&characterLook.asset.status==='approved'?[{asset:characterLook.asset,caption:suggestedCaption.length<=600?suggestedCaption:''}]:[]);
  setName(characterLook?characterLook.name+' version':'');setRights(false);setSameLook(false);setAnatomy(false);
 },[characterLook?.id]);
 const [steps,setSteps]=useState(200);const [seed,setSeed]=useState(42);
 const [busy,setBusy]=useState(false);const [notice,setNotice]=useState<string|null>(null);
 const pending=useRef<{signature:string;key:string}|null>(null);
 const active=history?.jobs.find(j=>['queued','running'].includes(j.status));
 const disabled=readOnly||busy||!!active||!history?.available||failed;
 async function train(){
  if(disabled)return;setBusy(true);setNotice(null);
  try{
   const signature=JSON.stringify([name,selected.map(i=>[i.asset.id,i.caption]),rights,steps,seed,characterLook?.id,sameLook,anatomy]);
   if(pending.current?.signature!==signature)pending.current={signature,key:crypto.randomUUID()};
   await api.createStyleJob(tenantId,projectId,styleBody(name,selected,rights,steps,seed,pending.current.key,characterLook?{look:characterLook,characterId:characterId??'',sameLook,anatomyReviewed:anatomy}:undefined));
   pending.current=null;setSelected([]);setRights(false);refresh();
  }catch(error){setNotice(error instanceof Error?error.message:'Could not start training.');}
  finally{setBusy(false);}
 }
 async function cancel(id:string){
  setBusy(true);try{await api.cancelStyleJob(tenantId,projectId,id);refresh();}
  catch(error){setNotice(error instanceof Error?error.message:'Could not cancel training.');}finally{setBusy(false);}
 }
 return <section className="studio-look-panel style-studio" aria-label={characterLook?"Character look training":"Project art style"}>
  <h3>{characterLook?"Character look training":"Project art style"}</h3>
  <p className="studio-hint">{characterLook?`Train a private version for ${characterLook.name} from this same character and outfit. Inspect hands, feet and limb count in every source; a good likeness can still have faulty anatomy.`:"Train a private style version from illustrations you choose. It can guide linework, colors and shading in new poses. Review each generated result; lighting can still differ."}</p>
  {failed&&<p role="alert">Style training could not be loaded. This server may need the updated API. <button type="button" className="studio-link" onClick={refresh}>Retry</button></p>}
  {history&&!history.available&&<p role="status">Style training is not enabled on this server.</p>}
  {history?.available&&<details><summary>{characterLook?"Train this reviewed look":"Train a new style version"}</summary>
   <fieldset disabled={disabled}>
    <Field label={characterLook?"Character version name":"Style version name"}><input maxLength={80} value={name} onChange={e=>setName(e.target.value)} placeholder="Evening illustrations" /></Field>
    <p className="studio-hint">{characterLook?"Choose 4–12 approved images of this character in this outfit, including the locked base. Start with the reviewed look tags, then describe the pose and visible scene in each caption.":"Choose 4–12 approved images with consistent rendering. Describe the content in each image so the model can distinguish the style from the person, outfit and scene."}</p>
    {library.failed&&<p role="alert">Approved images could not be loaded.</p>}
    <div className="style-image-picker" role="group" aria-label="Training images">{choices.map(asset=>{
     const chosen=selected.some(i=>i.asset.id===asset.id);
     return <label key={asset.id} className={chosen?'selected':''}>
      <input type="checkbox" aria-label={asset.name} checked={chosen} disabled={!chosen&&selected.length>=12} onChange={e=>{setRights(false);setSameLook(false);setAnatomy(false);setSelected(current=>e.target.checked?[...current,{asset,caption:suggestedCaption.length<=600?suggestedCaption:''}]:current.filter(i=>i.asset.id!==asset.id));}} />
      <LookImage tenantId={tenantId} projectId={projectId} asset={asset} label={asset.name} /><span>{asset.name}</span>
     </label>;
    })}</div>
    <p role="status">{selected.length} of 4–12 images selected</p>
    {selected.map(item=><div className="style-caption" key={item.asset.id}>
     <LookImage tenantId={tenantId} projectId={projectId} asset={item.asset} label={item.asset.name} />
     <Field label={`Content caption: ${item.asset.name}`}><textarea rows={3} maxLength={600} value={item.caption} onChange={e=>{setRights(false);setSameLook(false);setAnatomy(false);setSelected(current=>current.map(i=>i.asset.id===item.asset.id?{...i,caption:e.target.value}:i));}} placeholder="White hair, red scarf, navy coat, sitting on a chair…" /></Field>
    </div>)}
    <div className="style-settings"><Field label="Training steps"><input type="number" min={20} max={400} value={steps} onChange={e=>setSteps(Number(e.target.value))} /></Field>
     <Field label="Random seed"><input type="number" min={0} max={4294967295} value={seed} onChange={e=>setSeed(Number(e.target.value))} /></Field></div>
    {characterLook&&<>
     <label className="studio-check"><input type="checkbox" checked={sameLook} onChange={e=>setSameLook(e.target.checked)} /><span>Every selected image shows this same character and outfit, including the reviewed base.</span></label>
     <label className="studio-check"><input type="checkbox" checked={anatomy} onChange={e=>setAnatomy(e.target.checked)} /><span>I checked anatomy, hands, feet and limb count in every selected image.</span></label>
    </>}
    <label className="studio-check"><input type="checkbox" checked={rights} onChange={e=>setRights(e.target.checked)} /><span>I reviewed these images and captions and have rights to train on them.</span></label>
    <p className="studio-hint">Weights stay private in the Studio and are never included in exported games.</p>
    <button type="button" className="studio-primary" disabled={selected.length<4||!rights||!name.trim()||selected.some(i=>!i.caption.trim())||(!!characterLook&&(!sameLook||!anatomy||!selected.some(i=>i.asset.sha256===characterLook.source_sha256)))} onClick={()=>void train()}>{characterLook?"Train character version":"Train style version"}</button>
   </fieldset>
  </details>}
  {notice&&<p role="status">{notice}</p>}
  {history?.jobs.filter(job=>characterLook?job.kind==="character_look"&&job.look?.id===characterLook.id:job.kind!=="character_look").map(job=><article className="style-version" key={job.id}>
   <div><strong>{job.name}</strong><small>{job.images.length} images · {job.steps} steps · {new Date(job.created_at).toLocaleString()}</small></div>
   <p role={job.status==='running'?'status':undefined}>{styleStatus(job)}</p>
   {['queued','running'].includes(job.status)&&<><progress value={job.progress} max={job.steps} aria-label={`Training progress: ${job.name}`} />
    {!readOnly&&!job.cancel_requested&&<button type="button" className="studio-link" disabled={busy} onClick={()=>void cancel(job.id)}>Cancel training</button>}</>}
   <details><summary>Training record</summary>
    <ul>{job.images.map(i=><li key={i.asset_id}><strong>{i.name}:</strong> {i.caption}</li>)}</ul>
    {job.runtime&&<p>{Number(job.runtime.seconds??0).toFixed(0)} seconds · peak model memory {(Number(job.runtime.peak_allocated_bytes??0)/2**30).toFixed(2)} GiB</p>}
    {job.losses?.length&&<p>Final training loss: {job.losses.at(-1)?.toFixed(4)}. Training loss does not measure visual quality.</p>}
    {job.weights_sha256&&<p className="studio-hint">Version {job.id.slice(0,8)} · weights {job.weights_sha256.slice(0,12)}</p>}
   </details>
  </article>)}
 </section>;
}
