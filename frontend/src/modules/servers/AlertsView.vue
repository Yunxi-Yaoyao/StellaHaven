<script setup lang="ts">
// 告警设置：选择性添加规则（节点离线 / 监控项异常 / WG 链路中断）+ 规则管理 + 事件历史。
// 数据源：/alerts/* API；目标清单来自 nodes / monitors / map-topology。
import { computed, onMounted, ref } from "vue";
import Icon from "../../shell/Icon.vue";
import Dropdown from "../../shell/Dropdown.vue";
import {
  createRule, deleteRule, KIND_LABELS, listRules, patchRule,
  type AlertRule,
} from "../../api/alerts";
import { listNodes, listMonitors, type Node, type Monitor } from "../../api/servers";
import { getMapTopology, type MapLink } from "../../api/serverMap";
import { api } from "../../api/client";

interface AlertEvent {
  id: number; rule_id: number; event: "fired" | "resolved"; ts: string; message: string;
}

const rules = ref<AlertRule[]>([]);
const events = ref<AlertEvent[]>([]);
const nodes = ref<Node[]>([]);
const monitors = ref<Monitor[]>([]);
const links = ref<MapLink[]>([]);
const loading = ref(true);
const error = ref("");

// ── 添加规则 ──
const adding = ref(false);
const newKind = ref<AlertRule["kind"]>("node_offline");
const newTarget = ref<string | number | boolean | null>(null);
const newSeverity = ref<string | number | boolean | null>("warning");
const newEmail = ref(true);
const submitting = ref(false);

// 删除二次确认（破坏性操作）
const confirmDelete = ref<number | null>(null);

const KINDS: { value: AlertRule["kind"]; label: string; desc: string }[] = [
  { value: "node_offline", label: "节点离线", desc: "超过 2 分钟没有心跳" },
  { value: "monitor_down", label: "监控项异常", desc: "探测连续失败" },
  { value: "wg_link", label: "WG 链路中断", desc: "双向探测失败（红色）" },
];

const nodeName = computed(() => {
  const m = new Map<number, string>();
  nodes.value.forEach((n) => m.set(n.id, n.name));
  return (id: number | null) => (id != null ? m.get(id) ?? `#${id}` : "?");
});

const targetOptions = computed(() => {
  const taken = new Set(rules.value.map((r) => `${r.kind}:${r.target}`));
  if (newKind.value === "node_offline") {
    return nodes.value
      .filter((n) => n.status !== "removed" && !taken.has(`node_offline:${n.id}`))
      .map((n) => ({ value: String(n.id), label: n.name, desc: n.host }));
  }
  if (newKind.value === "monitor_down") {
    return monitors.value
      .filter((m) => !taken.has(`monitor_down:${m.id}`))
      .map((m) => ({ value: String(m.id), label: m.name, desc: `${nodeName.value(m.node_id)} · ${m.target}` }));
  }
  return links.value
    .filter((l) => l.target != null && !taken.has(`wg_link:${l.id}`))
    .map((l) => ({
      value: l.id,
      label: `${nodeName.value(l.source)} ↔ ${nodeName.value(l.target)}`,
      desc: `${l.source_interface} ↔ ${l.target_interface}`,
    }));
});

function targetLabel(kind: string, target: string): string {
  const opt = targetOptions.value; // 已排除已有规则，得从全量找
  void opt;
  if (kind === "node_offline") return nodes.value.find((n) => String(n.id) === target)?.name ?? target;
  if (kind === "monitor_down") return monitors.value.find((m) => String(m.id) === target)?.name ?? target;
  const l = links.value.find((x) => x.id === target);
  return l ? `${nodeName.value(l.source)} ↔ ${nodeName.value(l.target)} · ${l.source_interface}` : target.slice(0, 12) + "…";
}

function targetLink(kind: string, target: string): string {
  if (kind === "node_offline") return `/status/${target}`;
  if (kind === "monitor_down") {
    const m = monitors.value.find((x) => String(x.id) === target);
    return m ? `/status/${m.node_id}` : "/status";
  }
  return "/status";
}

async function submit() {
  if (newTarget.value == null || submitting.value) return;
  submitting.value = true;
  error.value = "";
  try {
    const target = String(newTarget.value);
    await createRule({
      kind: newKind.value,
      target,
      label: targetLabel(newKind.value, target),
      link: targetLink(newKind.value, target),
      severity: (newSeverity.value as "warning" | "critical") || "warning",
      email: newEmail.value,
    });
    adding.value = false;
    newTarget.value = null;
    await reload();
  } catch (e) {
    error.value = (e as { detail?: string })?.detail || "添加失败，再试试喵~";
  } finally {
    submitting.value = false;
  }
}

async function toggleEnabled(rule: AlertRule) {
  await patchRule(rule.id, { enabled: !rule.enabled });
  rule.enabled = !rule.enabled;
}

async function toggleEmail(rule: AlertRule) {
  await patchRule(rule.id, { email: !rule.email });
  rule.email = !rule.email;
}

async function removeRule(rule: AlertRule) {
  if (confirmDelete.value !== rule.id) {
    confirmDelete.value = rule.id;
    setTimeout(() => { if (confirmDelete.value === rule.id) confirmDelete.value = null; }, 3000);
    return;
  }
  confirmDelete.value = null;
  await deleteRule(rule.id);
  rules.value = rules.value.filter((r) => r.id !== rule.id);
}

function relTime(ts: string): string {
  const m = Math.floor((Date.now() - new Date(ts).getTime()) / 60000);
  if (m < 1) return "刚刚";
  if (m < 60) return `${m} 分钟前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小时前`;
  return `${Math.floor(h / 24)} 天前`;
}

async function reload() {
  rules.value = await listRules();
  events.value = await api<AlertEvent[]>("/alerts/events?limit=20");
}

onMounted(async () => {
  loading.value = true;
  try {
    const [n, m, topo] = await Promise.all([listNodes(), listMonitors(), getMapTopology()]);
    nodes.value = n;
    monitors.value = m;
    links.value = topo.links;
    await reload();
  } catch {
    error.value = "加载失败，刷新试试喵~";
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div class="alerts-view">
    <header class="head">
      <div>
        <h2 class="title">告警</h2>
        <p class="sub">给重要的节点、监控项和 WG 链路单独加告警，异常时站内铃铛和邮件会通知你喵~</p>
      </div>
      <button class="add-btn" @click="adding = !adding">
        <Icon :name="adding ? 'x' : 'plus'" :size="14" /> {{ adding ? "取消" : "添加告警" }}
      </button>
    </header>

    <!-- 添加面板 -->
    <Transition name="pop">
      <div v-if="adding" class="add-panel">
        <div class="kind-cards">
          <button
            v-for="k in KINDS" :key="k.value"
            class="kind-card" :class="{ active: newKind === k.value }"
            @click="newKind = k.value; newTarget = null"
          >
            <span class="kc-label">{{ k.label }}</span>
            <span class="kc-desc">{{ k.desc }}</span>
          </button>
        </div>
        <div class="add-row">
          <Dropdown v-model="newTarget" :options="targetOptions" />
          <Dropdown
            v-model="newSeverity"
            :options="[
              { value: 'warning', label: '普通（橙）' },
              { value: 'critical', label: '严重（红）' },
            ]"
          />
          <label class="email-check">
            <input v-model="newEmail" type="checkbox" /> 邮件提醒
          </label>
          <button class="submit-btn" :disabled="newTarget == null || submitting" @click="submit">
            {{ submitting ? "添加中…" : "添加" }}
          </button>
        </div>
        <div v-if="!targetOptions.length" class="hint">这个类型下没有可添加的目标了（可能都已加过）喵~</div>
      </div>
    </Transition>

    <div v-if="error" class="error">{{ error }}</div>
    <div v-if="loading" class="hint">加载中…</div>

    <!-- 规则列表 -->
    <div v-else-if="!rules.length && !adding" class="empty">
      还没有告警规则。点右上角「添加告警」，挑一个想盯的目标喵~
    </div>

    <div v-for="rule in rules" :key="rule.id" class="rule" :class="{ off: !rule.enabled }">
      <span class="state-dot" :class="rule.enabled ? rule.state : 'off'" :title="rule.enabled ? (rule.state === 'firing' ? '正在告警' : '正常') : '已停用'" />
      <div class="rule-main">
        <div class="rule-title">
          <span class="rule-label">{{ rule.label || targetLabel(rule.kind, rule.target) }}</span>
          <span class="tag">{{ KIND_LABELS[rule.kind] }}</span>
          <span class="tag sev" :class="rule.severity">{{ rule.severity === "critical" ? "严重" : "普通" }}</span>
        </div>
        <div class="rule-meta">
          连续 {{ rule.debounce }} 次异常触发 · firing 中每 {{ rule.repeat_minutes }} 分钟提醒
          <template v-if="rule.state === 'firing' && rule.message"> · {{ rule.message }}</template>
        </div>
      </div>
      <div class="rule-ops">
        <button class="mini" :class="{ on: rule.email }" title="邮件提醒" @click="toggleEmail(rule)">
          <Icon name="bell" :size="13" /> 邮件{{ rule.email ? "开" : "关" }}
        </button>
        <button class="mini" :class="{ on: rule.enabled }" @click="toggleEnabled(rule)">
          {{ rule.enabled ? "已启用" : "已停用" }}
        </button>
        <button
          class="mini danger" :class="{ confirm: confirmDelete === rule.id }"
          @click="removeRule(rule)"
        >
          {{ confirmDelete === rule.id ? "确认删除？" : "删除" }}
        </button>
      </div>
    </div>

    <!-- 事件历史 -->
    <template v-if="events.length">
      <h3 class="events-title">最近动态</h3>
      <div v-for="e in events" :key="e.id" class="event">
        <span class="ev-dot" :class="e.event" />
        <span class="ev-msg">{{ e.message || (e.event === 'fired' ? '触发告警' : '恢复正常') }}</span>
        <span class="ev-ts">{{ relTime(e.ts) }}</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.alerts-view { padding: 8px 4px; max-width: 860px; }

.head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.title { font-size: 22px; font-weight: 600; color: var(--text-hi); margin: 0 0 6px; letter-spacing: 0.5px; }
.sub { font-size: 13px; color: var(--text-lo); margin: 0; line-height: 1.6; }

.add-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 14px; border: none; border-radius: var(--radius-sm);
  background: var(--accent); color: var(--bg-base);
  font-size: 13px; font-weight: 500; cursor: pointer; flex-shrink: 0;
  transition: opacity var(--transition);
}
.add-btn:hover { opacity: 0.88; }

.add-panel {
  background: var(--bg-panel); border: 1px solid rgba(255,255,255,0.07);
  border-radius: var(--radius); padding: 16px; margin-bottom: 18px;
}
.kind-cards { display: flex; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
.kind-card {
  flex: 1; min-width: 150px; display: flex; flex-direction: column; gap: 4px;
  padding: 12px 14px; border-radius: var(--radius-sm);
  background: var(--bg-base); border: 1px solid rgba(255,255,255,0.07);
  color: var(--text-lo); cursor: pointer; text-align: left; transition: all var(--transition);
}
.kind-card:hover { border-color: var(--accent-dim); }
.kind-card.active { border-color: var(--accent); color: var(--accent); background: rgba(201,212,232,0.06); }
.kc-label { font-size: 13.5px; font-weight: 600; }
.kc-desc { font-size: 12px; color: var(--text-faint); }
.kind-card.active .kc-desc { color: var(--text-lo); }

.add-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.email-check { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text-lo); cursor: pointer; }
.email-check input { accent-color: var(--accent); }
.submit-btn {
  padding: 7px 18px; border: none; border-radius: var(--radius-sm);
  background: var(--accent); color: var(--bg-base); font-size: 13px; cursor: pointer;
}
.submit-btn:disabled { opacity: 0.4; cursor: default; }

.hint { font-size: 12.5px; color: var(--text-faint); padding: 8px 2px; }
.error { font-size: 13px; color: #e5605c; padding: 8px 2px; }
.empty {
  padding: 42px 0; text-align: center; font-size: 13.5px; color: var(--text-lo);
  border: 1px dashed rgba(255,255,255,0.12); border-radius: var(--radius);
}

.rule {
  display: flex; align-items: center; gap: 12px;
  background: var(--bg-panel); border: 1px solid rgba(255,255,255,0.06);
  border-radius: var(--radius); padding: 13px 16px; margin-bottom: 8px;
}
.rule.off { opacity: 0.55; }

.state-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.state-dot.ok { background: #5cb88a; }
.state-dot.off { background: #5c6474; }
.state-dot.firing { background: #e5605c; animation: pulse 1.4s ease-in-out infinite; }
@keyframes pulse { 50% { opacity: 0.35; } }

.rule-main { flex: 1; min-width: 0; }
.rule-title { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.rule-label { font-size: 14px; font-weight: 500; color: var(--text-hi); }
.tag {
  font-size: 11px; padding: 1px 8px; border-radius: 8px;
  background: rgba(255,255,255,0.06); color: var(--text-lo);
}
.tag.sev.critical { background: rgba(229,96,92,0.15); color: #e5605c; }
.rule-meta { font-size: 12px; color: var(--text-faint); margin-top: 3px; }

.rule-ops { display: flex; gap: 6px; flex-shrink: 0; flex-wrap: wrap; }
.mini {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 5px 10px; border-radius: var(--radius-sm); font-size: 12px;
  background: transparent; border: 1px solid rgba(255,255,255,0.1);
  color: var(--text-lo); cursor: pointer; transition: all var(--transition);
}
.mini:hover { border-color: var(--accent-dim); color: var(--text-hi); }
.mini.on { color: var(--accent); border-color: var(--accent-dim); }
.mini.danger:hover { color: #e5605c; border-color: rgba(229,96,92,0.5); }
.mini.danger.confirm { background: rgba(229,96,92,0.15); color: #e5605c; border-color: #e5605c; }

.events-title { font-size: 15px; font-weight: 600; color: var(--text-hi); margin: 22px 0 10px; }
.event {
  display: flex; align-items: baseline; gap: 10px;
  padding: 8px 4px; border-bottom: 1px solid rgba(255,255,255,0.04);
}
.ev-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; transform: translateY(-1px); }
.ev-dot.fired { background: #e5605c; }
.ev-dot.resolved { background: #5cb88a; }
.ev-msg { flex: 1; font-size: 13px; color: var(--text-lo); }
.ev-ts { font-size: 11.5px; color: var(--text-faint); flex-shrink: 0; }

.pop-enter-active, .pop-leave-active { transition: opacity 0.16s, transform 0.16s; }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: translateY(-4px); }

@media (max-width: 720px) {
  .rule { flex-wrap: wrap; }
  .rule-ops { width: 100%; }
}
</style>
