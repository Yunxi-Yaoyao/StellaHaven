import {test} from 'node:test';
import assert from 'node:assert/strict';
import {installLegacyBoundary} from '../e2e/notes-legacy-boundary.ts';

async function probe(url,method='GET'){
 let handler;const actions=[];
 await installLegacyBoundary({route:async(_pattern,callback)=>{handler=callback;}});
 const route={request:()=>({url:()=>url,method:()=>method}),abort:async reason=>{actions.push(['abort',reason]);},fallback:async()=>{actions.push(['fallback']);},continue:async()=>{actions.push(['continue']);},fulfill:async value=>{actions.push(['fulfill',value]);}};
 let error;try{await handler(route);}catch(e){error=e;}
 return {actions,error};
}
for(const url of ['https://example.invalid/notes','http://127.0.0.1:9999/documents/','http://localhost:15186/notes'])test(`outside denial: ${url}`,async()=>{
 const result=await probe(url);assert.match(result.error?.message,/Denied outside/);assert.deepEqual(result.actions,[['abort','blockedbyclient']]);
});
for(const path of ['/api/unknown','/auth/unknown','/documents/unexpected-id','/config/unexpected','/notes/preferences'])test(`unknown endpoint fails: ${path}`,async()=>{
 const result=await probe('http://127.0.0.1:15186'+path);assert.match(result.error?.message,/Unknown fixture endpoint/);assert.deepEqual(result.actions,[['abort','blockedbyclient']]);
});
test('known origin is not permission to use unknown methods',async()=>{
 const result=await probe('http://127.0.0.1:15186/navigation','DELETE');assert.match(result.error?.message,/Unknown fixture endpoint/);
});
test('navigation supplies Notes; API requests fall back only to explicit fixture handlers',async()=>{
 const navigation=await probe('http://127.0.0.1:15186/navigation');assert.equal(navigation.error,undefined);assert.deepEqual(navigation.actions[0][1].json.entries,[{id:'notes',visible:true}]);
 const document=await probe('http://127.0.0.1:15186/documents/doc-a');assert.equal(document.error,undefined);assert.deepEqual(document.actions,[['fallback']]);
});
