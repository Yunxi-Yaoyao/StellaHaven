<script setup lang="ts">
import {computed,ref} from 'vue';
import type {AuthClient,AuthProviderConfig} from '../../api/authProvider';
// Public configuration only. Secret display is owned by AuthProviderSettings.
const props=defineProps<{issuer:string;client?:Pick<AuthClient,'client_id'|'redirect_uris'|'scopes'>;endpoints?:Partial<AuthProviderConfig>}>();
const notice=ref('');
const rows=computed(()=>[
 ['Issuer',props.issuer],
 ...(props.client?[['Client ID',props.client.client_id],['Scopes',props.client.scopes.join(' ')],...props.client.redirect_uris.map((value,i)=>['精确回调 '+(i+1),value])]:[])
]);
const manualRows=computed(()=>[
 ['发现地址',props.endpoints?.discovery_url||props.issuer+'/.well-known/openid-configuration'],
 ['授权端点',props.endpoints?.authorization_endpoint||props.issuer+'/oauth/authorize'],['Token 端点',props.endpoints?.token_endpoint||props.issuer+'/oauth/token'],
 ['UserInfo 端点',props.endpoints?.userinfo_endpoint||props.issuer+'/oauth/userinfo'],['JWKS',props.endpoints?.jwks_uri||props.issuer+'/oauth/jwks']
]);
async function copy(value:string){try{await navigator.clipboard.writeText(value);notice.value='已复制';}catch{notice.value='无法访问剪贴板，请选中复制';}}
</script>
<template><section class="oidc-guide" aria-label="原站 OIDC 配置向导"><h3>在原站 / 客户端设置</h3><p>原生 OIDC 不需要注入脚本。先在 Stella 注册精确回调，再把下面的当前值填入原站的 OpenID Connect 设置；内外网入口共用这个稳定身份。</p><dl><div v-for="row in rows" :key="row[0]"><dt>{{row[0]}}</dt><dd><code>{{row[1]}}</code><button class="st-button" type="button" :aria-label="'复制 '+row[0]" @click="copy(row[1]||'')">复制</button></dd></div></dl><p v-if="!client">尚未选择应用。请在 Stella 单点登录中选择已有应用，回调须读取它的实际登记值，不使用推测示例。</p><details class="manual-endpoints"><summary>原站要求手动填写端点时</summary><dl><div v-for="row in manualRows" :key="row[0]"><dt>{{row[0]}}</dt><dd><code>{{row[1]}}</code><button class="st-button" type="button" :aria-label="'复制 '+row[0]" @click="copy(row[1]||'')">复制</button></dd></div></dl></details><p>Client Secret 只填在原站服务端的秘密设置中，不粘贴到浏览器脚本、CSS、URL 或这里的示例。更改回调后，原站也需同步同一个精确地址；Stella 不会自动修改原站。</p><p role="status">{{notice}}</p></section></template>
<style scoped>
.oidc-guide{min-width:0}h3{font-size:16px;margin:0 0 10px}p{font-size:14px;color:var(--text-lo);line-height:1.7}dl{margin:16px 0}dl>div{display:grid;grid-template-columns:115px minmax(0,1fr);gap:10px;margin:10px 0;align-items:start}dt{font-size:13px;color:var(--text-lo);padding-top:8px}dd{display:flex;gap:10px;align-items:flex-start;margin:0;min-width:0}code{overflow-wrap:anywhere;line-height:1.6;padding-top:7px;flex:1;font-size:13px}button:not(.st-button){flex-shrink:0;border:1px solid var(--control-border,var(--accent-dim));border-radius:7px;background:var(--bg-raised);color:var(--text-hi);padding:8px 12px;cursor:pointer;min-height:36px}summary{cursor:pointer;font-size:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--bg-base);padding:14px;border-radius:8px;font-size:13px;line-height:1.7}button:not(.st-button):focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:3px}@media(max-width:600px){dl>div{grid-template-columns:1fr;gap:0}dt{padding:0}button:not(.st-button){min-height:44px}}
</style>
