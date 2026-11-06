import {useRef,useState} from 'react';
import type {KeyboardEvent,PointerEvent} from 'react';
import {api} from '../lib/api';
import {CreditCost} from '../components/CreditCost';
import {imageItem} from '../site/creditsModel';
import type {NarrativeImage} from '../lib/api';
import {useNarrativeImage} from './characterImages';
import {Field} from './FormFields';
import type {PoseJob} from './poseModel';
import {initialRegion,moveRegion,resizeRegion,repairBody,validRegion} from './poseRepairModel';
import type {RepairBox} from './poseRepairModel';
import {StudioDialog} from './StudioDialog';

export function PoseRepairDialog({tenantId,projectId,characterId,asset,disabled,onClose,onCreated}:{
  tenantId:string;projectId:string;characterId:string;asset:NarrativeImage;disabled:boolean;
  onClose:()=>void;onCreated:(job:PoseJob)=>void;
}){
  const width=asset.width!,height=asset.height!;
  const [box,setBox]=useState<RepairBox>(()=>initialRegion(width,height));
  const [instruction,setInstruction]=useState('');
  const [count,setCount]=useState(1);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState<string|null>(null);
  const pending=useRef<{signature:string;key:string}|null>(null);
  const url=useNarrativeImage(tenantId,projectId,asset.id,'image');
  const frame=useRef<HTMLDivElement>(null);
  const drag=useRef<{start:RepairBox;x:number;y:number;mode:'move'|'resize'}|null>(null);
  function start(mode:'move'|'resize',event:PointerEvent<HTMLElement>){
    if(busy||disabled)return;
    event.preventDefault();event.stopPropagation();event.currentTarget.setPointerCapture(event.pointerId);
    drag.current={start:box,x:event.clientX,y:event.clientY,mode};
  }
  function move(event:PointerEvent<HTMLElement>){
    const item=drag.current;if(!item||busy||disabled)return;
    const scale=width/(frame.current?.clientWidth||width);
    setBox((item.mode==='resize'?resizeRegion:moveRegion)(item.start,(event.clientX-item.x)*scale,(event.clientY-item.y)*scale,width,height));
  }
  function key(event:KeyboardEvent<HTMLElement>){
    const delta:Record<string,[number,number]>={ArrowLeft:[-2,0],ArrowRight:[2,0],ArrowUp:[0,-2],ArrowDown:[0,2]};
    if(!delta[event.key]||disabled||busy)return;
    event.preventDefault();const [dx,dy]=delta[event.key];
    setBox((event.shiftKey?resizeRegion:moveRegion)(box,dx,dy,width,height));
  }
  async function generate(){
    if(busy||disabled)return;
    setBusy(true);setError(null);
    try{
      const signature=JSON.stringify([asset.id,box,instruction.trim(),count]);
      if(pending.current?.signature!==signature)pending.current={signature,key:crypto.randomUUID()};
      const next=await api.createPoseRepairJob(tenantId,projectId,characterId,repairBody(asset,box,instruction,count,pending.current.key));
      onCreated(next);
    }catch(reason){setError(reason instanceof Error?reason.message:'Could not start the repair.');}
    finally{setBusy(false);}
  }
  return <StudioDialog label="Repair pose area" onClose={onClose}><div className="studio-peek-body">
    <div className="studio-section-heading"><h2>Repair pose area</h2><button type="button" className="studio-link" onClick={onClose}>Close</button></div>
    <p>Move the box over the detail to fix. Only that area is redrawn; the original stays unchanged.</p>
    <div className="pose-repair-workbench">
      <div ref={frame} className="pose-repair-frame" style={{aspectRatio:`${width}/${height}`}}>
        {url?<img src={url} alt="Original pose to repair" draggable={false}/>:<span role="status">Loading image…</span>}
        <div role="group" tabIndex={0} aria-label="Repair area. Arrow keys move; Shift and arrow keys resize."
          className="pose-repair-box" style={{left:`${box[0]/width*100}%`,top:`${box[1]/height*100}%`,width:`${(box[2]-box[0])/width*100}%`,height:`${(box[3]-box[1])/height*100}%`}}
          onPointerDown={event=>start('move',event)} onPointerMove={move} onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}} onLostPointerCapture={()=>{drag.current=null;}} onKeyDown={key}>
          <span className="pose-repair-handle" onPointerDown={event=>start('resize',event)}/>
        </div>
      </div>
      <fieldset disabled={busy||disabled}>
        <p className="studio-hint">Drag the box to move it and its corner to resize. Arrow keys move; Shift + arrows resize.</p>
        <div className="pose-repair-coordinates">
          {['Left','Top','Width','Height'].map((label,index)=><Field key={label} label={label}><input type="number" min={index<2?0:16} step={1}
            value={index<2?box[index]:box[index]-box[index-2]} onChange={event=>{
              const value=Number(event.target.value);if(!Number.isFinite(value))return;
              if(index<2)setBox(moveRegion(box,index===0?value-box[0]:0,index===1?value-box[1]:0,width,height));
              else setBox(resizeRegion(box,index===2?value-(box[2]-box[0]):0,index===3?value-(box[3]-box[1]):0,width,height));
            }}/></Field>)}
        </div>
        {!validRegion(box,width,height)&&<p role="alert">Select at most a quarter of the image.</p>}
        <Field label="Correction"><textarea rows={4} maxLength={300} value={instruction} onChange={event=>setInstruction(event.target.value)} placeholder="For example: a natural left hand resting on the thigh"/></Field>
        <Field label="Repair candidates"><select value={count} onChange={event=>setCount(Number(event.target.value))}><option value={1}>1</option><option value={2}>2</option></select></Field>
        <p className="studio-hint">Uses this pose’s reviewed look and trained versions. Compare the repaired detail and edges before approving.</p>
        <button type="button" className="studio-primary" disabled={!url||!instruction.trim()||!validRegion(box,width,height)} onClick={()=>void generate()}>{busy?'Starting repair…':'Generate repair'}</button>
        <CreditCost item={imageItem({purpose:'character_portrait',pose:true,repair:true})} quantity={count} />
      </fieldset>
    </div>
    {error&&<p role="alert">{error}</p>}
  </div></StudioDialog>;
}
