<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { api } from '../../api/client';
import Dropdown from '../../shell/Dropdown.vue';
const props = defineProps<{ kind: 'drive' | 'gallery' }>();
const emit = defineEmits<{ close: []; saved: [] }>();
const cfg = ref<any>(null);
const busy = ref(false);
const message = ref('');
const success = ref(false);
const secret = ref('');
const authOptions = [{ value:'manual',label:'在原服务登录' }, ...(props.kind === 'drive' ? [{value:'token',label:'管理员专用 Token 登录'}] : [{value:'oidc',label:'使用已有 OIDC 登录'}])];
const clearToken = ref(false);
const reveal = ref(false);
const revealedStored = ref(false);
const secretEdited = ref(false);
async function revealToken() {
  if (reveal.value) { reveal.value = false; return; }
  if (cfg.value?.has_token && !secretEdited.value) {
    try {
      const value = await api<{token:string}>('/drive/connection/token', {method:'POST'});
      secret.value = value.token; revealedStored.value = true;
    } catch (e) { message.value = err(e); return; }
  }
  reveal.value = true;
}
const err = (e: any) => typeof e?.detail === 'string' ? e.detail : '请求失败，请检查地址和字段格式';
onMounted(async () => {
  try { cfg.value = await api(`/${props.kind}/connection`); }
  catch (e) { message.value = err(e); }
});
async function submit(test: boolean) {
  busy.value = true; message.value = ''; success.value = false;
  const { has_token, ...fields } = cfg.value;
  try {
    const result = await api<any>(`/${props.kind}/connection${test ? '/test' : ''}`, {
      method: test ? 'POST' : 'PUT',
      body: JSON.stringify({ ...fields, token: (secretEdited.value || !revealedStored.value) ? secret.value || null : null, clear_token: clearToken.value }),
    });
    if (test) { success.value = result.ok; message.value = `${result.message}。${result.warning || ''}`; }
    else { cfg.value = result; secret.value = ''; clearToken.value = false; reveal.value = false; revealedStored.value = false; secretEdited.value = false; success.value = true; message.value = '已保存连接设置'; emit('saved'); }
  } catch (e) { message.value = err(e); }
  finally { busy.value = false; }
}
</script>
<template>
  <div class="connection-overlay" @click.self="!busy && emit('close')" @keydown.esc="!busy && emit('close')">
    <section class="connection-dialog" role="dialog" aria-modal="true" aria-labelledby="connection-title">
      <header><h2 id="connection-title">{{ kind === 'drive' ? 'OpenList' : 'Immich' }} 连接设置</h2><button :disabled="busy" aria-label="关闭" @click="emit('close')">×</button></header>
      <p>仅连接已有服务；不会安装、启停或修改原服务。设置对本站生效，仅管理员可更改。</p>
      <form v-if="cfg" @submit.prevent="submit(false)">
        <div class="groups">
          <fieldset><legend>{{ kind === 'drive' ? '服务连接' : '图库入口' }}</legend>
            <template v-if="kind === 'drive'">
              <label>OpenList 服务地址<input v-model="cfg.service_url" required type="url" placeholder="http://服务器:5244/drive/openlist" /></label>
              <small>这是 Stella 后端能访问的 OpenList 地址，包含协议、端口及已有基础路径。网页通过 Stella 内嵌访问，无需另填 iframe 地址。</small>
            </template>
            <template v-else>
              <label>Immich 访问地址<input v-model="cfg.browser_url" required type="url" placeholder="https://photos.example.com" /></label>
              <small>浏览器直接访问此地址；端口可直接写在 URL 中。</small>
              <details><summary>高级连接</summary><label>后端健康检查地址（可选）<input v-model="cfg.upstream_url" type="url" /></label><label>yunxi.life 备用入口（可选）<input v-model="cfg.alternate_browser_url" type="url" /></label></details>
            </template>
          </fieldset>
          <fieldset><legend>服务器与认证</legend>
            <label>登录方式<Dropdown v-model="cfg.auth_mode" :options="authOptions" /></label>
            <template v-if="kind === 'drive' && cfg.auth_mode === 'token'">
              <div class="secret-state">{{ cfg.has_token ? 'Token 已配置' : 'Token 未配置' }}</div>
              <label>Token<input v-model="secret" :type="reveal ? 'text' : 'password'" :placeholder="cfg.has_token ? '已保存 · 留空不修改' : '输入 OpenList Token'" autocomplete="new-password" @input="secretEdited = true" /></label>
              <button type="button" @click="revealToken">{{ reveal ? '隐藏 Token' : cfg.has_token ? '查看已保存 Token' : '显示 Token' }}</button>
              <label class="check"><input v-model="clearToken" type="checkbox" />清除已保存 Token</label>
              <small>仅管理员可取得此 Token，普通用户仍使用自己的 OpenList 账号。建议使用最小权限 Token。</small>
            </template>
            <small v-else>账号密码在原服务填写，Stella 不保存。OIDC 必须已在原服务配置。</small>
          </fieldset>
        </div>
        <p v-if="message" role="status" :class="{ success }">{{ message }}</p>
        <p class="save-hint">“测试连接”只验证当前输入；“保存并应用”会保存地址与认证设置，并重新加载页面。</p>
        <footer><button type="button" :disabled="busy" @click="submit(true)">{{ busy ? '处理中…' : '测试连接' }}</button><button type="submit" :disabled="busy">保存并应用</button></footer>
      </form>
      <p v-else role="status">{{ message || '加载中…' }}</p>
    </section>
  </div>
</template>
<style scoped>
.connection-overlay{position:fixed;inset:0;background:#0009;display:grid;place-items:center;z-index:100;padding:20px}.connection-dialog{width:min(920px,100%);max-height:90vh;overflow:auto;background:var(--bg-panel,#1b1f2a);color:var(--text-hi,#f0f4f8);border:1px solid #ffffff20;border-radius:16px;padding:24px;box-sizing:border-box}header,footer{display:flex;align-items:center;justify-content:space-between;gap:12px}h2{font-size:18px;margin:0}p,small{font-size:12px;line-height:1.7;color:var(--text-lo,#b4bdce)}.groups{display:grid;grid-template-columns:1fr 1fr;gap:20px}fieldset{min-width:0;border:1px solid #ffffff18;border-radius:10px;padding:16px;display:flex;flex-direction:column;gap:16px}legend{padding:0 8px;font-size:13px}label{display:flex;flex-direction:column;gap:8px;font-size:12px}input,select{box-sizing:border-box;width:100%;padding:10px;border:1px solid #ffffff20;background:var(--bg-base,#14171f);border-radius:6px;color:inherit}.check{flex-direction:row;align-items:center}.check input{width:auto}button{padding:8px 16px;border:1px solid #ffffff25;background:var(--bg-raised,#252a36);color:inherit;border-radius:7px;cursor:pointer}button:disabled{opacity:.5;cursor:wait}footer{justify-content:flex-end;margin-top:20px}.success{color:#86d9ab}@media(max-width:700px){.groups{grid-template-columns:1fr}.connection-dialog{padding:16px}}
</style>
