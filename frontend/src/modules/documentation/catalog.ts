import snapshot from './apiSnapshot';
import {guides} from './guides';
export interface DocPage {id:string;section:'guide'|'api';group:string;title:string;body:string}
type Schema = { [key:string]:unknown; $ref?:string; type?:string; format?:string; minimum?:number; exclusiveMinimum?:number; maximum?:number; exclusiveMaximum?:number; properties?:Record<string,Schema>; required?:string[]; items?:Schema; anyOf?:Schema[]; oneOf?:Schema[]; enum?:unknown[]; default?:unknown; description?:string; example?:unknown };
interface Operation {summary?:string;description?:string;tags?:string[];parameters?:{name:string;in:string;required?:boolean;description?:string;schema?:Schema}[];requestBody?:{required?:boolean;content:Record<string,{schema?:Schema}>};responses:Record<string,{description?:string;content?:Record<string,{schema?:Schema}>}>;[key:string]:unknown}
const schema=snapshot.schema as unknown as {paths:Record<string,Record<string,Operation>>;components:{schemas:Record<string,Schema>}};
export function resolveSchema(value:Schema):Schema {return value.$ref?schema.components.schemas[value.$ref.split('/').at(-1)!]||value:value;}
const json=(value:unknown)=>'```json\n'+JSON.stringify(value,null,2)+'\n```';
const cell=(value:unknown)=>String(value??'—').replace(/\|/g,'\\|').replace(/\n/g,' ');
function typeOf(raw:Schema):string {const s=resolveSchema(raw);return s.anyOf?.map(typeOf).join(' / ')||s.oneOf?.map(typeOf).join(' / ')||s.type||String(raw.$ref?.split('/').at(-1)||'未限定');}
function fields(raw:Schema):string {const s=resolveSchema(raw);return s.properties?'|字段|类型|必填|说明|\n|---|---|---|---|\n'+Object.entries(s.properties).map(([k,v])=>`|${cell(k)}|${cell(typeOf(v))}|${s.required?.includes(k)?'是':'否'}|${cell(v.description||resolveSchema(v).description)}|`).join('\n'):'';}
// Move one representable float, not +/- 1 or an epsilon that can skip a narrow range.
function adjacent(value:number,direction:1|-1):number {
 if(value===0)return direction*Number.MIN_VALUE;
 const view=new DataView(new ArrayBuffer(8));
 view.setFloat64(0,value);
 view.setBigUint64(0,view.getBigUint64(0)+((value>0)===(direction>0)?1n:-1n));
 return view.getFloat64(0);
}
function numericSample(s:Schema):number|string {
 const replace='<REPLACE_ME: 约束冲突或无可安全表示的数值；请按类型、上下界和枚举填写>';
 const bounds=[s.minimum,s.exclusiveMinimum,s.maximum,s.exclusiveMaximum];
 if(bounds.some(value=>value!==undefined&&(typeof value!=='number'||!Number.isFinite(value))))return replace;
 const integer=s.type==='integer';
 // Be conservative about JS precision; never print an unsafe integer as a concrete example.
 const safe=Number.MAX_SAFE_INTEGER;
 const valid=(value:unknown):value is number=>typeof value==='number'&&Number.isFinite(value)&&Math.abs(value)<=safe
  &&(!integer||Number.isSafeInteger(value))
  &&(s.minimum===undefined||value>=s.minimum)&&(s.maximum===undefined||value<=s.maximum)
  &&(s.exclusiveMinimum===undefined||value>s.exclusiveMinimum)&&(s.exclusiveMaximum===undefined||value<s.exclusiveMaximum)
  &&(!s.enum||s.enum.includes(value));
 if(valid(s.default))return s.default;
 if(s.enum)return s.enum.find(valid) ?? replace;
 let lower=Math.max(-safe,s.minimum??-safe),upper=Math.min(safe,s.maximum??safe);
 if(s.exclusiveMinimum!==undefined)lower=Math.max(lower,integer?Math.floor(s.exclusiveMinimum)+1:adjacent(s.exclusiveMinimum,1));
 if(s.exclusiveMaximum!==undefined)upper=Math.min(upper,integer?Math.ceil(s.exclusiveMaximum)-1:adjacent(s.exclusiveMaximum,-1));
 if(integer){lower=Math.ceil(lower);upper=Math.floor(upper);}
 if(lower>upper)return replace;
 const value=Math.max(lower,Math.min(0,upper));
 return valid(value)?value:replace;
}
export function sample(raw:Schema,name='',depth=0):unknown {
 const s=resolveSchema(raw);
 if(/password|secret|token|authorization|cookie|code_verifier|^code$|capability/i.test(name))return '<REPLACE_ME>';
 if(depth>6)return '<见结构定义>';
 if(s.type==='integer'||s.type==='number')return numericSample(s);
 if(s.default!==undefined && s.default!==null)return s.default;
 if(s.enum?.length)return s.enum[0];
 if(s.anyOf||s.oneOf)return sample((s.anyOf||s.oneOf)!.find(v=>v.type!=='null')||{},name,depth+1);
 if(s.type==='object'||s.properties)return Object.fromEntries(Object.entries(s.properties||{}).filter(([key])=>s.required?.includes(key)).map(([key,v])=>[key,sample(v,key,depth+1)]));
 if(s.type==='array')return [sample(s.items||{},name,depth+1)];
 if(s.type==='boolean')return false;
 if(s.format==='uuid')return '00000000-0000-4000-8000-000000000000';
 if(s.format==='date-time')return '2026-01-01T00:00:00Z';
 if(s.format==='binary')return '<FILE>';
 if(s.type==='null')return null;
 return '<'+(name||'VALUE')+'>';
}
function expanded(raw:Schema,seen:string[]=[],depth=0):Schema {
 if(depth>9)return raw;
 if(raw.$ref){if(seen.includes(raw.$ref))return raw;return expanded(resolveSchema(raw),[...seen,raw.$ref],depth+1);}
 const result:Schema={...raw};
 if(raw.properties)result.properties=Object.fromEntries(Object.entries(raw.properties).map(([k,v])=>[k,expanded(v,seen,depth+1)]));
 if(raw.items)result.items=expanded(raw.items,seen,depth+1);
 if(raw.anyOf)result.anyOf=raw.anyOf.map(v=>expanded(v,seen,depth+1));
 if(raw.oneOf)result.oneOf=raw.oneOf.map(v=>expanded(v,seen,depth+1));
 return result;
}
const authNames:Record<string,string>={'cookie-access':'Stella 登录会话 Cookie','anonymous':'公开接口（无登录依赖）','optional-cookie':'可选 Stella 会话，行为视当前身份而定','conditional-cookie':'按请求条件要求 Stella 会话','cookie-refresh':'Stella 刷新会话 Cookie','agent-bearer':'Agent 专用 Bearer（兼容历史 query token）','oidc-userinfo':'OIDC userinfo Bearer token','oidc-client':'OIDC 客户端认证'};
function operationBody(method:string,path:string,op:Operation):string {
 let body=`## ${method} ${path}\n${op.summary||''}\n\n${op.description||''}\n\n## 认证与权限\n认证：${authNames[String(op['x-stella-auth-type'])]||op['x-stella-auth-type']}。\n\n管理提升：${op['x-stella-elevation']}。${op['x-stella-auth-detail']||''}\n\n见「认证与会话」理解会话、Origin 与提升策略；所有权限以服务器实际检查为准。\n\n## 路径与查询参数\n`;
 body+=op.parameters?.length?'|名称|位置|类型|必填|说明|\n|---|---|---|---|---|\n'+op.parameters.map(p=>`|${cell(p.name)}|${cell(p.in)}|${cell(typeOf(p.schema||{}))}|${p.required?'是':'否'}|${cell(p.description)}|`).join('\n'):'无声明参数。';
 if(op.parameters?.length)body+='\n\n<details><summary>完整参数定义（含默认值与约束）</summary>\n\n'+json(op.parameters.map(p=>({...p,schema:expanded(p.schema||{})})))+'\n\n</details>\n';
 body+='\n\n## 请求体与示例\n';
 if(op.requestBody){body+=op.requestBody.required?'请求体必填。\n\n':'请求体可选。\n\n';for(const [mime,entry] of Object.entries(op.requestBody.content)){body+=`### ${mime}\n${fields(entry.schema||{})}\n\n下面是结构示例，不是请求执行结果；占位符须替换，multipart 文件需用表单上传。\n\n${json(sample(entry.schema||{}))}\n\n完整请求结构：\n\n<details><summary>展开完整请求结构</summary>\n\n${json(expanded(entry.schema||{}))}\n\n</details>\n\n`;}}else body+='无声明请求体。不要添加未经接口支持的 JSON 字段。\n';
 body+='\n## 响应与错误\n下列为接口声明的状态与响应结构，不是实际调用回执；字节流、重定向与上游透传不能当作固定 JSON。401 请重新登录或更新正确凭据；403 检查管理提升；409 先处理冲突或维护要求；422 按字段校正输入，不盲目重试写入。\n\n';
 for(const [status,response] of Object.entries(op.responses)){body+=`### ${status}\n${response.description||'见响应结构'}\n\n`;for(const [mime,entry] of Object.entries(response.content||{})){body+=`${mime}\n\n`;if(mime.includes('json')&&op['x-stella-contract-status']!=='passthrough')body+=`响应字段示意（由结构生成，不是已执行结果；占位值以约束为准）：\n\n${json(sample(entry.schema||{}))}\n\n`;body+=`<details><summary>展开 ${status} 完整响应结构</summary>\n\n${json(expanded(entry.schema||{}))}\n\n</details>\n\n`;}}
 if(op['x-stella-contract-status']==='passthrough')body+='\n这是透传接口：响应由上游决定，Stella 不保证统一 JSON 外壳。\n';
 return body;
}
const intro:DocPage={id:'authentication',section:'api',group:'接入说明',title:'认证与会话',body:`## 基础地址与约定
API 与当前 Stella 主站同源，直接使用本文 method/path，不额外添加 /api 前缀。示例使用 https://stella.example.invalid，占位凭据均为 REPLACE_ME，不对应真实账号。

这里展示当前功能版本在隔离环境从真实 /openapi.json 导出的路由、请求与响应定义。页面只供阅读，没有试运行按钮，不会发送文档里的写请求。上游透传和 WebSocket 另有边界，不以 schema 宣称第三方服务已验证。

## 登录、刷新与退出
普通 API 使用 HttpOnly 的 stella_at 会话 Cookie，刷新使用 stella_rt；它们不是可粘贴到 Header 的 API Key。使用 /auth/login 获得会话，用 /auth/me 确认当前身份。刷新会旋转刷新凭据，勿并发重复刷新；退出或改密后的会话可能被撤销。

浏览器同源调用可使用 credentials: 'same-origin'；写请求必须来自部署信任的 Origin，不能伪造 Forwarded 头绕过。跨站、未知 Host 或未配置的 Origin 可能被拒绝，即使 Cookie 看似存在。


## 管理提升
唯一用户账号的有效会话即可管理，不另设管理密码。GET /auth/security 保留兼容状态形状，不是授权回退；旧 /auth/admin/* 与 PUT /auth/security 已退役，已认证请求返回 410。来源、资源归属、会话撤销与到期仍由服务器检查。

## Agent 与 OIDC
Agent 使用自己的 Bearer 凭据；历史 query token 仅为兼容，优先 Header，不能使用普通会话或 OIDC token 替代。OIDC 授权码、客户端凭据与 userinfo Bearer token 也不是普通 API 会话。每个接口显示其真实认证分类与提升策略。

## 错误处理
401 检查登录或凭据；403 检查 Origin、所有权与管理授权；404 不代表可以跨账号探测对象；409 处理冲突、版本或 maintenance_required；422 校正参数与请求体。具体状态以当前接口声明为准。认证错误、验证错误与业务结构化 detail 都可能出现，不要只按字符串解析。

写请求丢失响应时先查询确切对象或任务状态，不能一律自动重发。示例对象不是已经创建的数据；本中心不会替你登录、保存或发起备份。`};
const websockets:DocPage={id:'websockets',section:'api',group:'接入说明',title:'WebSocket 与事件',body:`## 不属于 OpenAPI 的连接
以下 ${snapshot.websockets.length} 个声明与 HTTP 单独计数。使用当前主站 wss 入口，浏览器携带当前会话 Cookie；对象频道还检查工作区/文档所有权，未授权或撤销会话会以 1008 关闭。服务端会在接收消息及空闲检查时重验，不延长会话活动时间。

## 文档与列表
- /ws/list/{workspace_id}：列表变化广播 list_changed，收到后重新读列表，不把通知当成完整业务数据。
- /ws/{doc_id}?device=DEVICE_LABEL：草稿上行使用 type: draft 的 JSON，正文存草稿槽，不能当成正文保存；正文保存广播 doc_saved。device 是设备标记，不是认证凭据。

草稿消息结构示例（仅文本示意，不自动发送）：

${json({type:'draft',content:'待保存的草稿正文',request_id:'request-example-1'})}

content 必须为字符串；可选 request_id 必须为 1–128 UTF-8 字节。成功提交后返回 draft_ack，含 request_id、draft_updated_at、content_hash 与 base_updated_at；只有收到对应确认才把草稿视为已提交。格式不合法或失去对象权限关闭 1008；数据库提交失败或结果不确定关闭 1011，不返回成功确认。断线后先核实草稿，不把断线当成没有写入。

## 通知铃铛
/ws/notifications 发送持久通知的即时提醒。断线重连后用 HTTP 通知列表和未读接口补齐，不假定 WebSocket 保存了全部离线事件。

## 代理 WebSocket 的边界
外部网站的代理升级和网页项目资源入口可能由 ASGI/中间件处理，不是本表新增的通用 WebSocket API。它们受各自入口、启动票据、会话和上游协议约束；不能用上述三条声明推断外部服务已连通。`};
export const pages:DocPage[]=[...guides.map(g=>({...g,section:'guide' as const})),intro,websockets,...snapshot.operations.map(({method,path})=>{
 const op=schema.paths[path]![method.toLowerCase()]!;
 return {id:`${method.toLowerCase()}:${path}`,section:'api' as const,group:op.tags?.[0]||'其他接口',title:`${method} ${path}`,body:operationBody(method,path,op)};
}),...Object.entries(schema.components.schemas).sort(([a],[b])=>a.localeCompare(b)).map(([name,value])=>({id:`model:${name}`,section:'api' as const,group:'数据模型',title:`模型 · ${name}`,body:`## ${name}\n${value.description||'此模型描述接口字段与约束。'}\n\n这是结构定义，不是服务器返回的实例。递归结构中的 $ref 指向同名数据模型，可在本栏目搜索模型名称。\n\n${json(value)}`}))];
export const apiCoverage=snapshot.coverage;
