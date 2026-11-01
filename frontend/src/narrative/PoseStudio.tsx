import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import type { NarrativeImage } from "../lib/api";
import { LookImage, useCharacterLooks } from "./CharacterLooks";
import { CandidateLookReview, useLookReviewFlags } from "./CandidateLookReview";
import { isActive } from "./characterModel";
import {compatibleAdapters} from "./styleModel";
import {StyleStudio,useStyleJobs} from "./StyleStudio";
import { Field } from "./FormFields";
import { refreshLibrary, useApprovedAssets } from "./libraryAssets";
import { lookReferences } from "./lookModel";
import { useNarrativeImage } from "./characterImages";
import { POSE_PRESETS, poseBody, poseStatus } from "./poseModel";
import type { PoseHistory, PoseJob, PoseView, PoseReference } from "./poseModel";
import { bindAsset, expressionId, setSprite } from "./stageModel";
import type { StoryDraft } from "./types";
import "./poses.css";

export function PoseStudio({ id, story, tenantId, projectId, readOnly, onChange, onError }: {
  id:string; story:StoryDraft; tenantId:string; projectId:string; readOnly:boolean;
  onChange:(story:StoryDraft,group?:string)=>void; onError:(message:string)=>void;
}) {
  const looks=useCharacterLooks(tenantId,projectId,id);
  const library=useApprovedAssets(tenantId,projectId);
  const [extraId,setExtraId]=useState("");
  const [view,setView]=useState<PoseView>("detail");
  const [confirmed,setConfirmed]=useState(false);
  useEffect(()=>{setExtraId("");setConfirmed(false);},[looks.look?.id]);
  const choices=lookReferences(library.assets??[],id).filter(asset=>asset.sha256!==looks.look?.source_sha256);
  const extra=choices.find(asset=>asset.id===extraId);
  const latest=useRef(story); latest.current=story;
  const [history,setHistory]=useState<PoseHistory|null>(null);
  const styles=useStyleJobs(tenantId,projectId,!!history?.capabilities.styles);
  const [styleId,setStyleId]=useState("");
  const [strength,setStrength]=useState(0.5);
  const style=compatibleAdapters(styles.history?.jobs??[],looks.look).find(j=>j.id===styleId);
  const [notice,setNotice]=useState<string|null>(null);
  const [failed,setFailed]=useState(false);
  const [revision,setRevision]=useState(0);
  const [pose,setPose]=useState(POSE_PRESETS[0]);
  const [count,setCount]=useState(1);
  const [transparent,setTransparent]=useState(true);
  const [busy,setBusy]=useState(false);
  const pending=useRef<{signature:string;key:string}|null>(null);
  const active=history?.jobs.find(item=>isActive(item.job));
  const activeKey=history?.jobs.filter(item=>isActive(item.job)).map(item=>item.job.id).join(",")??"";
  useEffect(()=>{
    const controller=new AbortController();
    const load=()=>api.listPoseJobs(tenantId,projectId,id,controller.signal).then(value=>{
      if(!controller.signal.aborted){setHistory(value);setFailed(false);}
    }).catch(()=>{if(!controller.signal.aborted)setFailed(true);});
    void load();
    // Poll the server list even while idle: jobs may have been started in another view.
    const timer=window.setInterval(()=>void load(),activeKey?1500:10000);
    return ()=>{window.clearInterval(timer);controller.abort();};
  },[tenantId,projectId,id,revision,activeKey]);
  const jobs=history?.jobs??[];
  const results=jobs.flatMap(item=>item.job.assets.map(asset=>({asset,item})));
  const reviews=useLookReviewFlags(tenantId,projectId,results.map(item=>item.asset));
  const refresh=()=>setRevision(value=>value+1);
  async function generate(){
    if(busy||readOnly||active||failed||!history?.capabilities.available)return;
    setBusy(true);setNotice(null);
    try{
      const signature=JSON.stringify([looks.look?.id,pose.trim(),count,transparent,extra?.id,view,confirmed,style?.id,strength]);
      if(pending.current?.signature!==signature)pending.current={signature,key:crypto.randomUUID()};
      const next=await api.createPoseJob(tenantId,projectId,id,poseBody(looks.look,pose,count,
        transparent&&history.capabilities.transparent,pending.current.key,extra?{asset:extra,view,confirmed}:undefined,style?{style,strength}:undefined));
      pending.current=null;
      setHistory(current=>current?{...current,jobs:[next,...current.jobs]}:current);refresh();
    }catch(error){setNotice(error instanceof Error?error.message:"Could not start this pose.");}
    finally{setBusy(false);}
  }
  async function cancel(item:PoseJob){
    setBusy(true);
    try{await api.cancelImageJob(tenantId,projectId,item.job.id);refresh();}
    catch(error){setNotice(error instanceof Error?error.message:"Could not cancel this pose.");}
    finally{setBusy(false);}
  }
  async function approve(asset:NarrativeImage){
    if(readOnly||busy)return;
    setBusy(true);
    try{const next=asset.status==="approved"?asset:await api.approveNarrativeAsset(tenantId,projectId,asset.id);
      refreshLibrary();refresh();return next;
    }catch(error){onError(error instanceof Error?error.message:"Could not approve this pose.");}
    finally{setBusy(false);}
  }
  async function use(asset:NarrativeImage,item:PoseJob){
    const next=await approve(asset);if(!next)return;
    try{
      const bound=bindAsset(latest.current,next);
      const expression=expressionId(bound.story,id,item.pose);
      onChange(setSprite(bound.story,id,expression,bound.key));
      setNotice(`Added “${expression}” to On stage. Select it on a scene or line.`);
    }catch(error){onError(error instanceof Error?error.message:"Could not use this pose.");}
  }
  async function discard(asset:NarrativeImage){
    if(readOnly||busy)return;setBusy(true);
    try{await api.discardNarrativeImage(tenantId,projectId,asset.id);refreshLibrary();refresh();}
    catch(error){setNotice(error instanceof Error?error.message:"Could not discard this pose.");}
    finally{setBusy(false);}
  }
  return <section className="studio-look-panel pose-studio" aria-label="Character poses">
    <h3>Poses from a reviewed look</h3>
    <p className="studio-hint">Keep the approved face, hair and outfit while drawing a new pose. Check each result before using it.</p>
    {failed&&<p role="alert">Pose jobs could not be loaded. <button type="button" className="studio-link" onClick={refresh}>Retry</button></p>}
    {!history&&!failed&&<p role="status">Loading pose jobs…</p>}
    {history&&!history.capabilities.available&&<p className="studio-hint">The pose model is not enabled on this server.</p>}
    {looks.error&&<p role="alert">{looks.error}</p>}
    {!looks.look&&looks.ready&&<p className="studio-hint">Lock and select a reviewed look above to generate poses.</p>}
    <div className="pose-workbench">
      {looks.look&&<LookImage tenantId={tenantId} projectId={projectId} asset={looks.look.asset} label={`Primary look and rendering: ${looks.look.name}`} />}
      <fieldset disabled={readOnly||busy||!!active||!looks.look||looks.look.asset.status!=="approved"||!history?.capabilities.available||failed}>
        {(history?.capabilities.max_references??1)>1&&<div className="pose-ref-picker">
          <Field label="Additional approved view"><select value={extraId} onChange={event=>{setExtraId(event.target.value);setConfirmed(false);}}>
            <option value="">None — use the primary image</option>{choices.map(asset=><option key={asset.id} value={asset.id}>{asset.name}</option>)}
          </select></Field>
          {library.failed&&<p role="alert">Approved views could not be loaded.</p>}
          {extra&&<>
            <LookImage tenantId={tenantId} projectId={projectId} asset={extra} label="Additional view to review" />
            <Field label="View shown"><select value={view} onChange={event=>setView(event.target.value as PoseView)}>
              <option value="detail">Detail or closer view</option><option value="front">Front</option><option value="side">Side</option><option value="back">Back</option>
            </select></Field>
            <label className="pose-transparent"><input type="checkbox" checked={confirmed} onChange={event=>setConfirmed(event.target.checked)} />I reviewed this as the same character and outfit</label>
          </>}
          <p className="studio-hint">The primary image guides linework, colors, shading and lighting. An extra view supplies missing shape and garment details. Check the result for style drift.</p>
        </div>}
        {history?.capabilities.styles&&<div>
          <Field label="Trained rendering version"><select value={styleId} disabled={styles.failed} onChange={event=>setStyleId(event.target.value)}>
            <option value="">Use reference rendering only</option>
            {compatibleAdapters(styles.history?.jobs??[],looks.look).map(j=><option key={j.id} value={j.id}>{j.kind==="character_look"?"This look: ":"Style: "}{j.name} · {j.id.slice(0,8)}</option>)}
          </select></Field>
          {styles.failed&&<p role="alert">Style versions could not be loaded. <button type="button" onClick={styles.refresh}>Retry</button></p>}
          {style&&<Field label={`Style strength · ${strength.toFixed(1)}`}><input type="range" min={0.1} max={1} step={0.1} value={strength} onChange={event=>setStrength(Number(event.target.value))} /></Field>}
          <p className="studio-hint">Train a project style in Look, or this character below. Check anatomy, light and linework in every result.</p>
        </div>}
        <Field label="Pose"><textarea rows={3} maxLength={300} value={active?.pose??pose} onChange={event=>setPose(event.target.value)} /></Field>
        <div className="pose-presets" role="group" aria-label="Pose ideas">{POSE_PRESETS.map(value=><button type="button" className="studio-link" key={value} onClick={()=>setPose(value)}>{value}</button>)}</div>
        <Field label="Candidates"><select value={count} onChange={event=>setCount(Number(event.target.value))}>{[1,2,3,4].map(n=><option key={n}>{n}</option>)}</select></Field>
        <label className="pose-transparent"><input type="checkbox" checked={transparent&&!!history?.capabilities.transparent} disabled={!history?.capabilities.transparent} onChange={event=>setTransparent(event.target.checked)} />Transparent stage sprite</label>
        <button type="button" className="studio-primary" disabled={!pose.trim()||(!!extra&&!confirmed)} onClick={()=>void generate()}>{active?"Generating…":`Generate ${count===1?"pose":`${count} poses`}`}</button>
      </fieldset>
    </div>
    {active&&<div className="studio-job" role="status"><progress max={active.job.count} value={active.job.progress} aria-label="Pose generation progress" /><span>{poseStatus(active.job)}</span>
      {!readOnly&&!active.job.cancel_requested&&<button type="button" className="studio-link" disabled={busy} onClick={()=>void cancel(active)}>Cancel</button>}</div>}
    {active?.references&&<p className="studio-hint" role="status">This job uses {active.references.map(reference=>`${reference.view}: ${reference.name}`).join("; ")}. Its references stay fixed while it runs.</p>}
    {jobs[0]&&!isActive(jobs[0].job)&&<p role="status">{poseStatus(jobs[0].job)}</p>}
    {notice&&<p role="status" className="studio-notice">{notice}</p>}
    {reviews.failed&&<p role="status">Some look feedback could not be loaded. Open Compare look to check a result.</p>}
    {!!results.length&&<div className="pose-results">{results.map(({asset,item})=>{
      const inUse=Object.values(story.characters[id]?.sprites??{}).some(key=>story.assets[key]?.sha256===asset.sha256);
      return <article className="pose-result" key={asset.id}>
        <LookImage tenantId={tenantId} projectId={projectId} asset={asset} label={item.pose} />
        {!!item.references?.length&&<details><summary>References used</summary><div className="pose-source-list">
          {item.references.map(reference=><FrozenReference key={reference.asset_id} tenantId={tenantId} projectId={projectId} reference={reference} />)}
        </div></details>}
        {item.style_adapter&&<small>Style: {item.style_adapter.name} · strength {item.style_adapter.strength}</small>}
        <small>Look: {item.look.name} · seed {String(asset.provenance.seed??"—")}</small>
        <CandidateLookReview tenantId={tenantId} projectId={projectId} asset={asset} readOnly={readOnly} flags={reviews.flags} />
        <div className="studio-actions">
          {asset.status==="candidate"&&<button type="button" className="studio-secondary" disabled={readOnly||busy} onClick={()=>void approve(asset)}>Approve</button>}
          {story.schema_version==="2"&&<button type="button" className="studio-secondary" disabled={readOnly||busy||inUse} onClick={()=>void use(asset,item)}>{inUse?"Added to stage":"Use on stage"}</button>}
          {!inUse&&<button type="button" className="studio-link studio-danger" disabled={readOnly||busy} onClick={()=>void discard(asset)}>Discard</button>}
        </div>
      </article>;
    })}</div>}
    {history?.capabilities.character_training&&looks.look&&<StyleStudio key={looks.look.id} tenantId={tenantId} projectId={projectId} readOnly={readOnly} characterLook={looks.look} characterId={id} />}
  </section>;
}


function FrozenReference({tenantId,projectId,reference}:{tenantId:string;projectId:string;reference:PoseReference}){
  const url=useNarrativeImage(tenantId,projectId,reference.asset_id,"thumbnail");
  return <figure>{url?<img src={url} alt={`${reference.view}: ${reference.name}`} />:<span>Image unavailable</span>}
    <figcaption>{reference.view}: {reference.name}</figcaption></figure>;
}
