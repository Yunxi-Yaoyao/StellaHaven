import {api} from './client';
import type {WebProject,ProjectFile} from './webProjects';
export interface ProjectDirectory {id:string;path:string;kind:'directory'}
export type FileProject = Omit<WebProject,'files'> & {directories?:ProjectDirectory[];entry_file_id?:string|null;files:(ProjectFile&{size?:number})[]};
export const setProjectEntry=(root:string,fileId:string,expectedEntry:string|null)=>api<FileProject>(`/web-project-files/${root}/entry`,{method:'PATCH',body:JSON.stringify({file_id:fileId,expected_entry_file_id:expectedEntry})});
export const copyProjectAsset=(root:string,path:string,targetDocId:string,requestId:string,signal?:AbortSignal)=>api<{url:string;filename:string}>(`/web-projects/${root}/copy-asset`,{method:'POST',signal,body:JSON.stringify({path,target_doc_id:targetDocId,request_id:requestId})});
