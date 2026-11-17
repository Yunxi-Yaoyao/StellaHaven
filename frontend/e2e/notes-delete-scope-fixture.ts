// Browser integration API fixture, NOT the Python backend or PostgreSQL proof.
// Implements the published scope contract so the production bundle crosses a real HTTP boundary.
import {createHash} from 'node:crypto';
type Row={id:string;parent_id:string|null;workspace_id:string};
type Request={workspace_id:string;doc_id?:string;mode:string;cascade:boolean};
export function scopeFixture(active:()=>Row[],trash:()=>Row[]){
 function preview(req:Request){
  const rows=[...active(),...trash()],ids=new Set<string>(req.doc_id?[req.doc_id]:[]);
  let changed=true;while(changed){changed=false;for(const d of rows)if(d.parent_id&&ids.has(d.parent_id)&&!ids.has(d.id)){ids.add(d.id);changed=true;}}
  const target_ids=req.mode==='empty-trash'?trash().map(d=>d.id):req.cascade?[...ids]:[req.doc_id!];
  const topology=rows.map(d=>[d.id,d.parent_id,trash().some(t=>t.id===d.id)]).sort((a,b)=>String(a[0]).localeCompare(String(b[0])));
  const scope_token=createHash('sha256').update(JSON.stringify([req,topology])).digest('hex');
  return {...req,scope_token,target_ids:target_ids.sort(),descendant_count:Math.max(0,ids.size-1)};
 }
 function valid(token:string|null,req:Request){return !!token&&token===preview(req).scope_token;}
 return {preview,valid};
}
