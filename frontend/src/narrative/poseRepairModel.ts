import type {NarrativeImage} from '../lib/api';
export type RepairBox=[number,number,number,number];
export function initialRegion(width:number,height:number):RepairBox{
  const left=Math.floor(width/3),top=Math.floor(height/3);
  return [left,top,left+Math.max(16,Math.floor(width/3)),top+Math.max(16,Math.floor(height/6))];
}
export function validRegion(box:RepairBox,width:number,height:number):boolean{
  const [left,top,right,bottom]=box;
  return box.every(Number.isInteger)&&left>=0&&top>=0&&right<=width&&bottom<=height
    &&right-left>=16&&bottom-top>=16&&(right-left)*(bottom-top)<=width*height/4;
}
export function moveRegion(box:RepairBox,dx:number,dy:number,width:number,height:number):RepairBox{
  const w=box[2]-box[0],h=box[3]-box[1];
  const left=Math.max(0,Math.min(width-w,Math.round(box[0]+dx)));
  const top=Math.max(0,Math.min(height-h,Math.round(box[1]+dy)));
  return [left,top,left+w,top+h];
}
export function resizeRegion(box:RepairBox,dx:number,dy:number,width:number,height:number):RepairBox{
  return [box[0],box[1],Math.max(box[0]+16,Math.min(width,Math.round(box[2]+dx))),
    Math.max(box[1]+16,Math.min(height,Math.round(box[3]+dy)))];
}
export function repairBody(asset:NarrativeImage,box:RepairBox,text:string,count:number,key:string){
  const instruction=text.replace(/\s+/g,' ').trim();
  if(asset.status==='discarded'||asset.media_type!=='image/png'||!asset.width||!asset.height)throw new Error('Choose an available pose image.');
  if(!validRegion(box,asset.width,asset.height))throw new Error('Select an area inside the image, at least 16 pixels per side and at most a quarter of it.');
  if(!instruction||instruction.length>300||/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(instruction))throw new Error('Describe the correction in 1–300 characters.');
  if(!Number.isInteger(count)||count<1||count>2)throw new Error('Choose 1–2 candidates.');
  return {asset_id:asset.id,box,instruction,count,idempotency_key:key};
}
