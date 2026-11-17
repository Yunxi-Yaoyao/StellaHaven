<script setup lang="ts">
import {computed} from 'vue';
import HelpHint from './HelpHint.vue';
import {expandCallbacks,type CallbackDraft} from './clientCallbacks';
const model=defineModel<CallbackDraft>({required:true});
const values=computed(()=>expandCallbacks(model.value));
function paths(index:number,event:Event){model.value.web[index]!.paths=(event.target as HTMLTextAreaElement).value.split('\n');}
</script>
<template>
 <section class="callback-editor" aria-label="应用回调设置">
  <div class="section-head"><h4>应用自己的地址<HelpHint label="应用地址与回调说明">分别填写此应用的公网、内网地址；每个地址只允许下方列出的用途路径，不会自动补齐其他地址的路径。</HelpHint></h4><button class="st-button" type="button" @click="model.web.push({origin:'',paths:['']})">添加应用地址</button></div>

  <div v-for="(row,index) in model.web" :key="index" class="web-row">
   <div class="row-head"><span>地址 {{index+1}}</span><button class="st-button" type="button" :aria-label="'移除应用地址 '+(index+1)" @click="model.web.splice(index,1)">移除地址</button></div>
   <div class="fields"><label>应用地址<input v-model="row.origin" :aria-label="'应用地址 '+(index+1)" placeholder="https://photos.example.com:443" autocomplete="off" spellcheck="false"/></label>
   <label>回调用途路径<textarea :value="row.paths.join('\n')" @input="paths(index,$event)" :aria-label="'回调用途路径 '+(index+1)" aria-describedby="callback-path-help" rows="2" placeholder="每行一个 / 开头的准确路径" spellcheck="false"/></label></div>
  </div>
  <details class="help"><summary>路径怎么填？</summary><p id="callback-path-help">从原应用的官方 OIDC 设置说明中确认路径。例如 Immich 的网页登录是 /auth/login，账号关联是 /user-settings；其他应用请填写它自己的准确路径，而不是照抄。</p></details>
  <div v-for="(uri,index) in model.native" :key="uri" class="retained"><div><strong>Immich移动App<HelpHint label="原生回调说明">完整原生回调，独立保留，不与网站域名拼接。</HelpHint></strong><code>{{uri}}</code></div><button class="st-button" type="button" aria-label="移除Immich移动App回调" @click="model.native.splice(index,1)">移除</button></div>
  <details v-if="model.compatibility.length" data-legacy-callbacks><summary>旧登记 · 保留 {{model.compatibility.length}} 条</summary><p>包含历史 HTTP 地址或未归类完整地址，保持原值，不自动迁移或补全。只在确认不再使用后移除。</p><div v-for="(uri,index) in model.compatibility" :key="index" class="retained"><code>{{uri}}</code><button class="st-button" type="button" :aria-label="'移除旧登记 '+(index+1)" @click="model.compatibility.splice(index,1)">移除</button></div></details>
  <details data-exact-callbacks><summary>完整白名单 · {{values.length}} 条</summary><p>只接受这些完整地址的精确匹配；保存后仍需在原应用后台同步配置。</p><code v-for="(uri,index) in values" :key="index" class="exact-uri">{{uri}}</code></details>
 </section>
</template>
<style scoped>
.callback-editor{min-width:0;margin:18px 0;color:var(--text-hi)}.section-head,.row-head,.retained{display:flex;gap:12px;align-items:center;justify-content:space-between}h4{font-size:15px;font-weight:550;margin:0}.section-head{flex-wrap:wrap}.web-row{margin:12px 0;padding:14px;background:var(--bg-panel);border:1px solid var(--control-border,var(--accent-dim));border-radius:10px}.row-head{font-size:12px;color:var(--text-lo);margin-bottom:12px}.fields{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:14px}label{display:flex;flex-direction:column;gap:7px;font-size:13px;color:var(--text-lo);min-width:0}input,textarea{box-sizing:border-box;width:100%;min-width:0;background:var(--bg-base);color:var(--text-hi);border:1px solid var(--control-border,var(--accent-dim));border-radius:7px;font:inherit;padding:10px;line-height:1.6}textarea{resize:vertical}input::placeholder,textarea::placeholder{color:var(--text-lo)}p,summary,small{font-size:13px;line-height:1.7;color:var(--text-lo)}p{margin:8px 0 12px}details{margin:12px 0}summary{cursor:pointer;min-height:32px}.retained{margin:12px 0;align-items:flex-start;min-width:0}.retained>div{min-width:0}strong{font-size:14px;font-weight:550}code,small{display:block;overflow-wrap:anywhere}.exact-uri{font-size:13px;line-height:1.8;margin:4px 0}code{font-size:13px;line-height:1.7;color:var(--text-hi)}button:not(.st-button){flex-shrink:0;min-height:36px;border:1px solid var(--control-border,var(--accent-dim));border-radius:7px;background:var(--bg-raised);color:var(--text-hi);padding:7px 10px;font:inherit;font-size:12px;cursor:pointer}button:not(.st-button):hover{border-color:var(--accent)}button:not(.st-button):focus-visible,input:focus-visible,textarea:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:3px}@media(max-width:600px){.fields{grid-template-columns:1fr}.web-row{padding:12px}button:not(.st-button){min-height:44px}.retained{gap:8px}.section-head{gap:8px}}
</style>
