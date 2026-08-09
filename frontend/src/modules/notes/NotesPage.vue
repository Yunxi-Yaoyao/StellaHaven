<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { useNotesStore } from "../../stores/notes";
import DocList from "./DocList.vue";
import DocEditor from "./DocEditor.vue";
import TrashPanel from "./TrashPanel.vue";

const store = useNotesStore();
const currentId = ref<string | null>(null);
const trashOpen = ref(false);
const ready = ref(false);

// 列表频道：任何文档变动（保存/新建/删除/还原）→ 刷新列表 + 回收站
// 别的设备改了标题，这边左侧实时跟上，不用手动刷新
let listWs: WebSocket | null = null;
let listWsTimer: ReturnType<typeof setTimeout> | null = null;
let listWsDead = false; // 主动关闭标记：组件卸载后不再重连

function connectListWs() {
  if (!store.workspaceId || listWsDead) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  listWs = new WebSocket(`${proto}://${location.host}/ws/list/${store.workspaceId}`);
  listWs.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === "list_changed") {
        store.refreshList();
        store.refreshTrash();
      }
    } catch {
      /* 忽略坏消息 */
    }
  };
  listWs.onclose = () => {
    listWs = null;
    if (!listWsDead) listWsTimer = setTimeout(connectListWs, 3000); // 断线重连
  };
}

onMounted(async () => {
  await store.bootstrap(); // 默认用户+工作区，首次自动建好
  ready.value = true;
  connectListWs();
  // 默认打开最新一篇
  if (store.docs.length > 0) currentId.value = store.docs[0].id;
});

onUnmounted(() => {
  listWsDead = true;
  if (listWsTimer) clearTimeout(listWsTimer);
  listWs?.close();
});

async function onOpen(id: string) {
  trashOpen.value = false;
  if (id === "__new__") {
    const doc = await store.createNew();
    currentId.value = doc.id;
  } else {
    currentId.value = id;
  }
}

function onSaved() {
  store.refreshList();
}

function onDeleted() {
  currentId.value = store.docs[0]?.id ?? null;
}
</script>

<template>
  <div class="notes-page" v-if="ready">
    <DocList :current-id="currentId" :trash-open="trashOpen" @open="onOpen" @show-trash="trashOpen = true" />
    <TrashPanel v-if="trashOpen" @close="trashOpen = false" />
    <DocEditor
      v-else-if="currentId"
      :key="currentId"
      :doc-id="currentId"
      @saved="onSaved"
      @deleted="onDeleted"
    />
    <div v-else class="blank">
      <div class="blank-icon">📝</div>
      <p>选一篇，或者新建一篇开始写</p>
    </div>
  </div>
  <div v-else class="loading">Stella 正在醒来…</div>
</template>

<style scoped>
.notes-page {
  display: flex;
  height: calc(100vh - 56px); /* 减去 content 区 padding */
  border-radius: var(--radius);
  overflow: hidden;
}
.blank {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  background: var(--bg-panel);
  border-radius: 0 var(--radius) var(--radius) 0;
  color: var(--text-faint);
}
.blank-icon { font-size: 36px; opacity: 0.6; }
.loading {
  height: 100%;
  display: grid;
  place-items: center;
  color: var(--text-faint);
}
</style>
