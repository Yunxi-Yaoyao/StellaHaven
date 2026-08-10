<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { storeToRefs } from "pinia";
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide, forceX, forceY, type SimulationNodeDatum, type SimulationLinkDatum } from "d3-force";
import { useNotesStore } from "../../stores/notes";
import { listAllLinks } from "../../api/notes";
import Icon from "../../shell/Icon.vue";

const emit = defineEmits<{ close: []; open: [id: string] }>();
const store = useNotesStore();
const { docs, tags, docTags } = storeToRefs(store);

interface GNode extends SimulationNodeDatum {
  id: string;
  label: string;
  kind: "doc" | "tag";
  x: number;
  y: number;
}
interface GLink extends SimulationLinkDatum<GNode> {
  source: string | GNode;
  target: string | GNode;
}

const nodes = ref<GNode[]>([]);
const links = ref<GLink[]>([]);
const W = ref(800);
const H = ref(560);
const containerEl = ref<HTMLElement | null>(null);

let sim: ReturnType<typeof forceSimulation<GNode>> | null = null;
let resizeObs: ResizeObserver | null = null;

onMounted(async () => {
  // 尺寸跟随容器
  if (containerEl.value) {
    W.value = containerEl.value.clientWidth;
    H.value = containerEl.value.clientHeight;
    resizeObs = new ResizeObserver(() => {
      if (!containerEl.value) return;
      W.value = containerEl.value.clientWidth;
      H.value = containerEl.value.clientHeight;
      sim?.force("center", forceCenter(W.value / 2, H.value / 2));
      sim?.alpha(0.3).restart();
    });
    resizeObs.observe(containerEl.value);
  }

  // 数据：文档节点 + 标签节点 + 双链边 + 标签归属边
  const wikiLinks = await listAllLinks();
  const docIds = new Set(docs.value.map((d) => d.id));

  // 初始位置：中心周围随机散开（全挤在 (0,0) 会被斥力炸出画布）
  const jitter = () => (Math.random() - 0.5) * Math.min(W.value, H.value) * 0.6;
  const ns: GNode[] = [
    ...docs.value.map((d) => ({
      id: d.id, label: d.title, kind: "doc" as const,
      x: W.value / 2 + jitter(), y: H.value / 2 + jitter(),
    })),
    ...tags.value
      .filter((t) => docTags.value.some((r) => r.tag_id === t.id))
      .map((t) => ({
        id: "tag-" + t.id, label: "#" + t.name, kind: "tag" as const,
        x: W.value / 2 + jitter(), y: H.value / 2 + jitter(),
      })),
  ];
  const ls: GLink[] = [
    ...wikiLinks
      .filter((l) => docIds.has(l.source_id) && docIds.has(l.target_id))
      .map((l) => ({ source: l.source_id, target: l.target_id })),
    ...docTags.value
      .filter((r) => docIds.has(r.doc_id))
      .map((r) => ({ source: r.doc_id, target: "tag-" + r.tag_id })),
  ];

  nodes.value = ns;
  links.value = ls;

  sim = forceSimulation<GNode>(ns)
    .force("link", forceLink<GNode, GLink>(ls).id((n) => n.id).distance(80))
    .force("charge", forceManyBody().strength(-160))
    .force("center", forceCenter(W.value / 2, H.value / 2))
    .force("collide", forceCollide(28))
    // 引力缰绳：把整团往画布中心拉，防止斥力把节点甩飞
    .force("x", forceX(W.value / 2).strength(0.06))
    .force("y", forceY(H.value / 2).strength(0.06))
    .on("tick", () => {
      nodes.value = [...ns]; // 触发响应式
    });
});

onUnmounted(() => {
  sim?.stop();
  resizeObs?.disconnect();
});

// 拖拽节点
let dragging: GNode | null = null;
function onPointerDown(n: GNode, e: PointerEvent) {
  dragging = n;
  (e.target as HTMLElement).setPointerCapture(e.pointerId);
  sim?.alphaTarget(0.2).restart();
}
function onPointerMove(e: PointerEvent) {
  if (!dragging || !containerEl.value) return;
  const rect = containerEl.value.getBoundingClientRect();
  dragging.fx = e.clientX - rect.left;
  dragging.fy = e.clientY - rect.top;
}
function onPointerUp() {
  if (dragging) {
    dragging.fx = null;
    dragging.fy = null;
    dragging = null;
    sim?.alphaTarget(0);
  }
}

function onNodeClick(n: GNode) {
  if (n.kind === "doc") emit("open", n.id);
  else {
    // 点标签节点 → 切列表筛选
    store.filterTagId = n.id.replace("tag-", "");
    emit("close");
  }
}

const nodeColor = (kind: string) => (kind === "doc" ? "var(--accent)" : "var(--pink)");
const nodeR = (kind: string) => (kind === "doc" ? 10 : 7);
</script>

<template>
  <div class="graph-panel">
    <div class="head">
      <span><Icon name="link" :size="15" /> 图谱</span>
      <span class="tip">{{ nodes.length }} 节点 · {{ links.length }} 连线 · 点笔记节点打开，点标签节点筛选</span>
      <button class="back" @click="emit('close')">← 返回</button>
    </div>

    <div
      ref="containerEl"
      class="canvas"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
    >
      <svg :width="W" :height="H">
        <line
          v-for="(l, i) in links"
          :key="i"
          :x1="(l.source as GNode).x"
          :y1="(l.source as GNode).y"
          :x2="(l.target as GNode).x"
          :y2="(l.target as GNode).y"
          class="edge"
        />
        <g
          v-for="n in nodes"
          :key="n.id"
          :transform="`translate(${n.x},${n.y})`"
          class="node"
          @pointerdown="onPointerDown(n, $event)"
          @click="onNodeClick(n)"
        >
          <circle :r="nodeR(n.kind)" :fill="nodeColor(n.kind)" />
          <text :y="nodeR(n.kind) + 13" text-anchor="middle" class="label">{{ n.label }}</text>
        </g>
      </svg>
      <div v-if="nodes.length === 0" class="empty">还没有内容——先写几篇笔记、打几个标签、建几条 [[双链]] 吧</div>
    </div>
  </div>
</template>

<style scoped>
.graph-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border-radius: 0 var(--radius) var(--radius) 0;
  overflow: hidden;
}
.head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  font-size: 15px;
  font-weight: 600;
}
.tip { flex: 1; font-size: 11px; color: var(--text-faint); font-weight: 400; }
.back {
  padding: 5px 14px;
  border: 1px solid var(--accent-dim);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--accent);
  font-size: 12px;
  cursor: pointer;
}
.canvas { flex: 1; overflow: hidden; position: relative; }
.edge { stroke: var(--accent-dim); stroke-opacity: 0.35; stroke-width: 1; }
.node { cursor: pointer; }
.node circle { transition: r var(--transition); }
.node:hover circle { r: 13; }
.label { font-size: 10.5px; fill: var(--text-lo); pointer-events: none; }
.empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--text-faint);
  font-size: 13px;
}
</style>
