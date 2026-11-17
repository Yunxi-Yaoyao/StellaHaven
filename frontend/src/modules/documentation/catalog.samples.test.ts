import {afterAll,expect,it} from 'vitest';
import {writeFileSync} from 'node:fs';
import {pages,resolveSchema} from './catalog';
import api from './apiSnapshot';

// Extract the reader's actual JSON blocks; never reimplement the sample generator.
function requestBlocks(id:string):unknown[] {
 const body=pages.find(page=>page.id===id)!.body;
 const request=body.split('## 请求体与示例')[1]!.split('## 响应与错误')[0]!;
 return [...request.matchAll(/```json\n([\s\S]*?)\n```/g)].map(match=>JSON.parse(match[1]!));
}
afterAll(()=>{
 if(process.env.DOC_SAMPLE_EXAMPLES)writeFileSync(process.env.DOC_SAMPLE_EXAMPLES,JSON.stringify(
  api.operations.map(({method,path})=>({id:`${method.toLowerCase()}:${path}`,blocks:requestBlocks(`${method.toLowerCase()}:${path}`)})),null,2)+'\n');
});

it.each([
 {method:'post',path:'/alerts/v2/preview',fields:['node_id']},
 {method:'post',path:'/alerts/v2/rules',fields:['node_id']},
 {method:'put',path:'/alerts/v2/rules/{rule_id}',fields:['node_id','revision']},
])('generates schema-valid positive integers in $method $path',({method,path,fields})=>{
 const id=`${method}:${path}`;
 const value=requestBlocks(id)[0] as Record<string,unknown>;
 const paths=api.schema.paths as unknown as Record<string,Record<string,{requestBody:{content:Record<string,{schema:Parameters<typeof resolveSchema>[0]}>}}>>;
 const model=resolveSchema(paths[path]![method]!.requestBody.content['application/json']!.schema);
 for(const field of fields){
  const definition=resolveSchema(model.properties![field]!);
  expect(definition.type).toBe('integer');
  expect(definition.exclusiveMinimum).toBe(0);
  expect(Number.isSafeInteger(value[field])).toBe(true);
  expect(value[field],`${id}.${field}`).toBeGreaterThan(Number(definition.exclusiveMinimum));
 }
 expect(pages.find(page=>page.id===id)!.body).toContain('不是请求执行结果');
 expect(pages.find(page=>page.id==='authentication')!.body).toContain('示例对象不是已经创建的数据');
});
