<script setup lang="ts">
import {computed,ref} from 'vue';
const props=defineProps<{adapter:'generic'|'openlist'|'immich';mode:string;mainOrigin:string;id?:string;customEnabled:boolean;delivery:string;authMode?:string;hasReadyCode?:boolean}>();
const notice=ref('');
const loader=computed(()=>props.id?'<script src="'+props.mainOrigin+'/website-assets/'+props.id+'.js"><'+'/script>':'');
async function copy(){try{await navigator.clipboard.writeText(loader.value);notice.value='已复制加载器，不包含凭据';}catch{notice.value='复制失败，可选中代码手动复制';}}
</script>
<template>
 <section v-if="authMode==='oidc'||delivery==='loader'&&customEnabled" class="website-guide" aria-label="网站接入说明">
  <p v-if="authMode==='oidc'">原生单点登录不需要脚本。</p>
  <details v-if="authMode==='oidc'"><summary>在哪里配置单点登录？</summary>
   <p><strong>Stella：</strong>在<RouterLink to="/settings?section=authentication">单点登录设置</RouterLink>选择这个应用，登记原网站要求的精确回调，读取它的身份地址、Client ID 与密钥。</p>
   <p v-if="adapter==='immich'"><strong>Immich：</strong>管理 → 设置 → OAuth，填写 Stella 身份地址（Issuer）、Client ID、Client Secret 与 Scopes；保留原账号关联。</p>
   <p v-else-if="adapter==='openlist'"><strong>OpenList：</strong>管理 → 设置 → 单点登录，填写 Stella 应用的当前配置；回调使用 OpenList 显示的真实地址。</p>
   <p v-else><strong>原网站：</strong>在它的 OpenID Connect 登录设置填写所选应用的当前值；不同软件的回调不同，不按域名推测。</p>
   <p>Client Secret 只填在原网站服务端的密钥字段，不放入脚本、CSS 或 URL。</p>
  </details>
  <details v-if="delivery==='loader'&&customEnabled&&id"><summary>加载自定义外观代码</summary><p>仅自定义外观需要：将这条完整脚本放入原网站允许的自定义 HTML 区域。它加载此网站已保存的代码；浏览器须能访问 Stella 并携带有效会话，原站 CSP 或第三方 Cookie 限制仍可能阻止加载。</p><pre>{{loader}}</pre><button class="st-button" type="button" @click="copy">复制加载器</button></details>
  <p v-if="notice" role="status">{{notice}}</p>
 </section>
</template>
<style scoped>
.website-guide{min-width:0;margin:10px 0}p{font-size:14px;line-height:1.7;color:var(--text-lo);margin:8px 0}strong,a{color:var(--text-hi)}a{overflow-wrap:anywhere}summary{font-size:14px;cursor:pointer;min-height:36px;align-content:center}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px;line-height:1.7;background:var(--bg-base);padding:12px;border-radius:7px}button:not(.st-button){font:inherit;font-size:14px;border:1px solid var(--control-border,var(--accent-dim));border-radius:7px;background:var(--bg-raised);color:var(--text-hi);padding:7px 12px;min-height:38px;cursor:pointer}button:not(.st-button):focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:3px}@media(max-width:600px){button:not(.st-button),summary{min-height:44px}}
</style>
