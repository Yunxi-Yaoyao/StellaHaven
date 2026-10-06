<script setup lang="ts">
import {ref,onMounted,onBeforeUnmount} from 'vue';
import {captureNote,type Doc} from '../../api/notes';
import './notesModal.css';
const props=defineProps<{workspaceId:string}>();const emit=defineEmits<{close:[];created:[doc:Doc]}>();
const title=ref(''),content=ref(''),busy=ref(false),error=ref(''),titleInput=ref<HTMLInputElement|null>(null);
const controller=new AbortController();onMounted(()=>titleInput.value?.focus());onBeforeUnmount(()=>controller.abort());
async function submit(){if(busy.value||!props.workspaceId||!title.value.trim())return;busy.value=true;error.value='';try{const doc=await captureNote(props.workspaceId,title.value.trim(),content.value,controller.signal);if(!controller.signal.aborted){emit('created',doc);emit('close');}}catch{if(!controller.signal.aborted)error.value='保存失败，内容仍保留在这里，请重试';}finally{busy.value=false;}}
</script>
<template><Teleport to="body"><div class="notes-modal-mask" @click.self="!busy&&emit('close')"><form class="notes-modal quick-record-modal" role="dialog" aria-modal="true" aria-label="快捷记录" @submit.prevent="submit">
<header><h2>快捷记录</h2><button type="button" :disabled="busy" aria-label="关闭快捷记录" @click="emit('close')">×</button></header>
<p>保存到当前工作区的专属收件箱。首次保存才创建文件夹，不会覆盖同名笔记。</p>
<label>记录标题<input ref="titleInput" v-model="title" maxlength="200" required :disabled="busy" /></label><label>记录正文<textarea v-model="content" maxlength="200000" rows="8" :disabled="busy" /></label>
<p v-if="error" role="alert">{{error}}</p><footer><button type="submit" :disabled="busy||!workspaceId||!title.trim()">{{busy?'保存中…':'保存并打开'}}</button><button type="button" :disabled="busy" @click="emit('close')">取消</button></footer>
</form></div></Teleport></template>
<style scoped>.quick-record-modal label{display:grid;gap:6px;margin:12px 0;font-size:13px}.quick-record-modal input,.quick-record-modal textarea{width:100%;box-sizing:border-box;background:var(--bg-raised);color:var(--text-hi);border:1px solid var(--accent-dim);border-radius:var(--radius-sm);padding:10px;font:inherit}.quick-record-modal textarea{resize:vertical}.quick-record-modal footer{display:flex;gap:8px;justify-content:flex-end}</style>
