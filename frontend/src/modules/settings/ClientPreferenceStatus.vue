<script setup lang="ts">
import {computed,inject} from 'vue';
import {routeLocationKey} from 'vue-router';
import {clientPreferenceSync as sync} from './clientPreferenceSync';
const props=defineProps<{compact?:boolean}>();
const route=inject(routeLocationKey,undefined);
const handledInline=computed(()=>props.compact && route?.name==='settings' && route.query.section==='appearance' && ['error','conflict'].includes(sync.state.phase));
const reloadNotice=computed(()=>sync.state.phase==='synced' && sync.state.reloadRequired && !sync.state.reloadDismissed);
const visible=computed(()=>!handledInline.value && (['error','conflict','restoring'].includes(sync.state.phase) || reloadNotice.value));
const label=computed(()=>({error:'偏好同步未完成，本机输入已保留',conflict:'服务器偏好已改变，本机输入已保留',restoring:'正在恢复设置，偏好同步已暂停'}[sync.state.phase as 'error'|'conflict'|'restoring'] ?? '部分布局将在刷新后生效，请先保存当前工作。'));
</script>
<template>
  <section v-if="visible" data-client-preferences class="preference-status" :class="{compact,error:sync.state.phase==='error'}" :role="sync.state.phase==='error'?'alert':'status'" aria-label="账号偏好同步">
    <p>{{label}}<span v-if="sync.state.phase==='error' && sync.state.message">：{{sync.state.message}}</span></p>
    <div v-if="sync.state.phase==='conflict'" class="choices"><span>请选择保留本机输入，或应用服务器偏好。</span><button @click="sync.useLocal()">保留本机偏好</button><button @click="sync.useServer()">使用服务器偏好</button></div>
    <button v-if="sync.state.phase==='error'" @click="sync.retry()">重试偏好同步</button>
    <button v-if="reloadNotice" @click="sync.dismissReload()">知道了</button>
  </section>
</template>
<style scoped>
.preference-status{border:1px solid var(--accent-dim);background:var(--bg-panel);color:var(--text-hi);padding:12px 14px;border-radius:10px;margin:0 0 16px;font-size:13px;line-height:1.6;overflow-wrap:anywhere}.preference-status p{margin:0 0 7px}.preference-status p:last-child{margin-bottom:0}.hint{font-size:12px;color:var(--text-lo)}.choices{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:8px}button{font:inherit;border:1px solid var(--accent-dim);border-radius:7px;min-height:38px;padding:6px 11px;background:var(--bg-raised);color:var(--text-hi);cursor:pointer}button:focus-visible{outline:2px solid var(--accent);outline-offset:3px}.error{border-color:var(--warm,var(--pink))}.compact{flex:none;min-height:0;max-height:30%;overflow:auto;max-width:100%;margin:0;border-radius:0;padding-bottom:max(12px,env(safe-area-inset-bottom))}@media(max-width:600px){button{min-height:44px}}
</style>
