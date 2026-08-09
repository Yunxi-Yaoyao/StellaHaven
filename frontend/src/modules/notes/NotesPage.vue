<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { storeToRefs } from "pinia";
import { useNotesStore, type TreeNode } from "../../stores/notes";
import DocList from "./DocList.vue";
import DocEditor from "./DocEditor.vue";
import TrashPanel from "./TrashPanel.vue";
import AttachmentsPanel from "./AttachmentsPanel.vue";
import MoveDialog from "./MoveDialog.vue";

const store = useNotesStore();
const { pendingDelete } = storeToRefs(store);
const currentId = ref<string | null>(null);
const trashOpen = ref(false);
const attachOpen = ref(false);
const ready = ref(false);
const moving = ref<TreeNode | null>(null);

// 列表频道：任何文档变动（保存/新建/删除/还原）→ 刷新列表 + 回收站
let listWs: WebSocket | null = null;
let listWsTimer: ReturnType<typeof setTimeout> | null = null;
let listWsDead = false;

function connectListWs() {
  if (!store.workspaceId || listWsDead) return;
  if (listWs && listWs.readyState <= WebSocket.OPEN) return; // 已有活连接不重复开
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
    if (!listWsDead) listWsTimer = setTimeout(connectListWs, 3000);
  };
}

onMounted(async () => {
  await store.bootstrap();
  ready.value = true;
  connectListWs();
  if (store.docs.length > 0) currentId.value = store.docs[0].id;
});

onUnmounted(() => {
  listWsDead = true;
  if (listWsTimer) clearTimeout(listWsTimer);
  listWs?.close();
});

// 切换工作区 → 列表频道重连 + 打开新工作区的第一篇
async function onWsSwitched() {
  listWs?.close();
  listWs = null;
  connectListWs();
  trashOpen.value = false;
  currentId.value = store.docs[0]?.id ?? null;
}

async function onOpen(id: string) {
  trashOpen.value = false;
  attachOpen.value = false;
  currentId.value = id;
  // 打开 → 服务端已戳 last_viewed_at，稍后刷新最近查看
  setTimeout(() => store.refreshRecent(), 300);
}

async function onNewChild(node: TreeNode | null) {
  trashOpen.value = false;
  const doc = await store.createNew(node ? node.id : undefined);
  currentId.value = doc.id;
}

function onMove(node: TreeNode) {
  moving.value = node;
}

function onDel(node: TreeNode) {
  store.requestDelete(node as any);
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
    <DocList
      :current-id="currentId"
      :trash-open="trashOpen"
      :attach-open="attachOpen"
      @open="onOpen"
      @show-trash="trashOpen = true; attachOpen = false"
      @show-attachments="attachOpen = true; trashOpen = false"
      @new-child="onNewChild"
      @move="onMove"
      @del="onDel"
      @switched="onWsSwitched"
    />
    <AttachmentsPanel v-if="attachOpen" @close="attachOpen = false" @open="onOpen" />
    <TrashPanel v-else-if="trashOpen" @close="trashOpen = false" />
    <DocEditor
      v-else-if="currentId"
      :key="currentId"
      :doc-id="currentId"
      @saved="onSaved"
      @deleted="onDeleted"
      @open="onOpen"
    />
    <div v-else class="blank">
      <div class="blank-icon">📝</div>
      <p>选一篇，或者新建一篇开始写</p>
    </div>

    <!-- 移动对话框 -->
    <MoveDialog v-if="moving" :node="moving" @done="moving = null" @cancel="moving = null" />

    <!-- 删除三选框（有下挂时） -->
    <div v-if="pendingDelete" class="mask" @click.self="pendingDelete = null">
      <div class="dialog">
        <div class="head">删除「{{ pendingDelete.doc.title }}」</div>
        <div class="body">这篇下面还挂着 {{ pendingDelete.childCount }} 篇子页面，怎么处理？</div>
        <div class="btns">
          <button class="danger" @click="store.doDelete(pendingDelete.doc.id, true).then(onDeleted)">
            一起删除（{{ pendingDelete.childCount + 1 }} 篇进回收站）
          </button>
          <button @click="store.doDelete(pendingDelete.doc.id, false).then(onDeleted)">
            仅删此篇 · 子页上移一级
          </button>
          <button class="cancel" @click="pendingDelete = null">取消</button>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="loading">Stella 正在醒来…</div>
</template>

<style scoped>
.notes-page {
  display: flex;
  height: calc(100vh - 56px);
  border-radius: var(--radius);
  overflow: hidden;
  position: relative;
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
.loading { height: 100%; display: grid; place-items: center; color: var(--text-faint); }

.mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: grid;
  place-items: center;
  z-index: 100;
}
.dialog {
  width: 380px;
  background: var(--bg-panel);
  border: 1px solid var(--bg-raised);
  border-radius: var(--radius);
  overflow: hidden;
}
.head { padding: 14px 18px; font-size: 14px; font-weight: 600; }
.body { padding: 0 18px 14px; font-size: 13px; color: var(--text-lo); }
.btns { display: flex; flex-direction: column; gap: 8px; padding: 0 18px 16px; }
.btns button {
  padding: 9px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--accent-dim);
  background: transparent;
  color: var(--accent);
  font-size: 13px;
  cursor: pointer;
  transition: all var(--transition);
}
.btns button:hover { background: var(--bg-raised); }
.btns button.danger { border-color: var(--pink); color: var(--pink); }
.btns button.cancel { border-color: var(--text-faint); color: var(--text-faint); }
</style>
