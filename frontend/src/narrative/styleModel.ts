import type {NarrativeImage} from '../lib/api';
export interface StyleJob {
 id:string;name:string;status:string;progress:number;steps:number;seed:number;
 images:{asset_id:string;sha256:string;name:string;caption:string}[];
 weights_sha256:string|null;model_manifest_sha256:string;dataset_sha256:string;recipe_sha256:string;
 cancel_requested:boolean;error_code:string|null;losses:number[]|null;runtime:Record<string,string>|null;
 tracking_run_id:string|null;created_at:string;
}
export interface StyleHistory {jobs:StyleJob[];available:boolean}
export interface TrainingSelection {asset:NarrativeImage;caption:string}
export function trainingAssets(assets:NarrativeImage[]):NarrativeImage[]{
 return assets.filter(a=>a.status==='approved'&&a.media_type==='image/png'&&(a.width??0)>=64&&(a.height??0)>=64);
}
export function styleBody(name:string,images:TrainingSelection[],rights:boolean,steps:number,seed:number,key:string){
 name=name.trim();
 if(!name||name.length>80)throw new Error('Name this style version in 1–80 characters.');
 if(!rights)throw new Error('Confirm you have rights to train on these images.');
 if(images.length<4||images.length>12||new Set(images.map(i=>i.asset.sha256)).size!==images.length)throw new Error('Choose 4–12 different approved images.');
 if(!Number.isInteger(steps)||steps<20||steps>400||!Number.isInteger(seed)||seed<0||seed>4294967295)throw new Error('Choose 20–400 training steps and a valid seed.');
 const captions=images.map(({asset,caption})=>{
  caption=caption.replace(/\s+/g,' ').trim();
  if(asset.status!=='approved'||asset.media_type!=='image/png'||!caption||caption.length>600)throw new Error('Review a content caption for every approved image.');
  return {asset_id:asset.id,caption};
 });
 return {name,images:captions,rights_confirmed:true,steps,seed,idempotency_key:key};
}
export function styleStatus(job:StyleJob):string{
 if(job.status==='completed')return 'Ready to try in Poses — review the results before approving.';
 if(job.status==='cancelled')return 'Cancelled.';
 if(job.cancel_requested)return 'Cancelling…';
 if(job.status==='queued')return 'Waiting for the training worker…';
 if(job.status==='running')return job.progress?`Training ${job.progress} of ${job.steps} steps…`:'Preparing images and loading the model…';
 const messages:Record<string,string>={caption_too_long:'A caption exceeds the model token limit. Shorten the captions and start a new version.',gpu_busy:'The GPU stayed busy. Try again when other work finishes.',host_memory_busy:'Not enough system memory was available.',out_of_memory:'Training ran out of GPU memory.',reference_unavailable:'A selected image is no longer approved or available.',model_pin_mismatch:'The installed model or training recipe changed. Start a new version.'};
 return messages[job.error_code??'']??'Training failed. Start a new version to try again.';
}
