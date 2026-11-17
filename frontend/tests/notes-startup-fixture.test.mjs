import assert from 'node:assert/strict';
import test from 'node:test';
import {createNotesStartupFixture} from './fixtures/notesStartup.mjs';
const workspace='11111111-1111-4111-8111-111111111111';
const requests=[['GET','/notes-preferences'],['POST',`/notes-tools/templates/${workspace}/initialize`],['GET',`/notes-tools/templates/${workspace}`],['GET',`/web-projects/workspace/${workspace}/identities`],['GET',`/web-projects/workspace/${workspace}`],['GET',`/detached-sources?workspace_id=${workspace}`]];
test('startup reads model full defaults, initialized empty catalog and ordered empty project/source catalogs',()=>{
 const f=createNotesStartupFixture(workspace);
 assert.deepEqual(f.respond(...requests[0]).json,{revision:0,delete_action:'trash',ask_before_delete:true,font_size:16,line_height:1.8,read_width:800,code_line_numbers:false,code_wrap:true,directory_sort:'updated',hidden_folders:[]});
 assert.deepEqual(f.respond(...requests[1]).json,{root_id:'44444444-4444-4444-8444-444444444444',items:[],recent_ids:[]});
 assert.deepEqual(f.respond(...requests[1]),f.respond(...requests[2]));
 for(const request of requests.slice(3))assert.deepEqual(f.respond(...request),{status:200,json:[]});
 f.respond(...requests[0]).json.hidden_folders.push('not-persisted');assert.deepEqual(f.respond(...requests[0]).json.hidden_folders,[]);
});
test('guest and expired owner receive no private startup DTO',()=>{
 const f=createNotesStartupFixture(workspace);
 for(const request of requests)assert.deepEqual(f.respond(...request,false),{status:401,json:{detail:'fixture unauthenticated'}});
});
test('negative control: unknown method, workspace, suffix and query never match; writes are not accepted',()=>{
 const f=createNotesStartupFixture(workspace);
 for(const [method,target] of requests){
  assert.equal(f.respond('DELETE',target),null);
  assert.equal(f.respond(method,target+(target.includes('?')?'&':'?')+'unknown=1'),null);
 }
 for(const request of [['PATCH','/notes-preferences'],['PUT','/notes-preferences'],['GET','/notes-preferences/unknown'],['GET',`/notes-tools/templates/${workspace}/initialize`],['POST',`/notes-tools/templates/${workspace}/create`],['GET','/web-projects/workspace/other'],['GET','/detached-sources'],['GET','/detached-sources?workspace_id=other'],['GET',`/detached-sources?workspace_id=${workspace}&workspace_id=${workspace}`]])assert.equal(f.respond(...request),null);
});
