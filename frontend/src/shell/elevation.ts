import {reactive} from 'vue';
import type {ElevationCode} from '../api/client';
/** Inactive compatibility exports for pre-migration embedded callers. */
export const elevation=reactive({open:false,code:'admin_elevation_required' as ElevationCode,path:'',ready:false});
export function requestElevation(_code:ElevationCode,_path:string):Promise<boolean>{return Promise.resolve(false);}
export function finishElevation(_confirmed=false){elevation.open=false;elevation.ready=false;elevation.path='';}
