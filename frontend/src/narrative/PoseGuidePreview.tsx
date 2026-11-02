import type {BodyGuide} from './poseModel';
const bones=[[1,2],[1,5],[2,3],[3,4],[5,6],[6,7],[1,8],[8,9],[9,10],[1,11],[11,12],[12,13],[1,0],[0,14],[14,16],[0,15],[15,17]];
export function PoseGuidePreview({guide,frozen=false}:{guide:BodyGuide;frozen?:boolean}){
 return <figure className="pose-guide-preview"><svg viewBox={`0 0 ${guide.width} ${guide.height}`} role="img" aria-label={guide.label}>
   {bones.map(([a,b],i)=><line key={i} x1={guide.points[a][0]} y1={guide.points[a][1]} x2={guide.points[b][0]} y2={guide.points[b][1]} stroke={`hsl(${i*20} 85% 65%)`} strokeWidth={10}/>)}
   {guide.points.map(([x,y],i)=><circle key={i} cx={x} cy={y} r={6} fill="#fff"/>)}
 </svg><figcaption>{frozen?'Body guide used':'Body guide'}: {guide.label}</figcaption></figure>;
}
