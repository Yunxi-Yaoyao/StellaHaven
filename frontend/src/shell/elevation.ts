import { reactive } from 'vue';
import type { ElevationCode } from '../api/client';
export const elevation = reactive({open:false,code:'admin_elevation_required' as ElevationCode,path:'',ready:false});
let resolveRequest:((confirmed:boolean)=>void)|undefined;
export function requestElevation(code:ElevationCode,path:string):Promise<boolean> {
  // Parallel blocked actions are not queued for automatic execution.
  if (resolveRequest) return Promise.resolve(false);
  elevation.code=code; elevation.path=path; elevation.ready=false; elevation.open=true;
  return new Promise(resolve=>{resolveRequest=resolve;});
}
export function finishElevation(confirmed=false) { const resolve=resolveRequest; resolveRequest=undefined; elevation.open=false; elevation.ready=false; elevation.path=''; resolve?.(confirmed); }
