import {copy,type Data} from './types';
export type NavDraft={editor:Data;baseline:Data;revision:number;mode:'settings'|'group'|'card';tab:string;groupId:string;cardId:string;cardGroupId:string;uncertain:boolean};
// Deliberately memory-only: no account content in persistent/device storage.
// One bounded slot survives SPA unmount and same-tab reauthentication only.
let retained:{owner:string;draft:NavDraft}|null=null;
export function keepNavDraft(owner:string,draft:NavDraft){if(owner)retained={owner,draft:copy(draft)};}
export function readNavDraft(owner:string):NavDraft|null{return retained?.owner===owner?copy(retained.draft):null;}
export function forgetNavDraft(owner:string){if(retained?.owner===owner)retained=null;}
