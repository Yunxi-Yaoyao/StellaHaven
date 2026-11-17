<script setup lang="ts">
import HelpHint from "../settings/HelpHint.vue";
// 告警设置：节点上报中断 / 监控项异常 / WG 链路中断 + 规则管理 + 事件历史。
// 数据源：/alerts/* API；目标清单来自 nodes / monitors / map-topology。
import { computed, onMounted, ref, nextTick } from "vue";
import {useRoute,useRouter} from "vue-router";
import AlertIncidentList from "./AlertIncidentList.vue";
import AlertIncidentDetail from "./AlertIncidentDetail.vue";
import type {Metric} from "../../api/alertMetrics";
import Icon from "../../shell/Icon.vue";
import MetricAlertsPanel from './MetricAlertsPanel.vue';
import Dropdown from "../../shell/Dropdown.vue";
import {
  createRule, deleteRule, KIND_LABELS, listRules, patchRule,
  type AlertRule,
} from "../../api/alerts";
import { listNodes, listMonitors, type Node, type Monitor } from "../../api/servers";
import { getMapTopology, type MapLink } from "../../api/serverMap";


const route=useRoute(),router=useRouter();
const tab=computed({get:()=>route.query.alertTab==='history'?'history':'items',set:value=>{void router.replace({query:{...route.query,alertTab:value}});}});
const incidentId=computed(()=>{const n=Number(route.query.incident);return Number.isSafeInteger(n)&&n>0?n:undefined;});
function closeIncident(){const {incident,...query}=route.query;void router.replace({query});}
const metricPanel=ref<InstanceType<typeof MetricAlertsPanel>>();
const revision=ref(0);

const rules = ref<AlertRule[]>([]);

const nodes = ref<Node[]>([]);
const monitors = ref<Monitor[]>([]);
const links = ref<MapLink[]>([]);
const loading = ref(true);
const error = ref("");

// ── 添加规则 ──
const adding = ref(false);
type AddKind=AlertRule["kind"]|"cpu"|"network.rate"|"network.volume";
const newKind = ref<AddKind>("node_offline");
const metricKind=computed(()=>["cpu","network.rate","network.volume"].includes(newKind.value));
async function chooseKind(value:AddKind){newKind.value=value;newTarget.value=null;if(metricKind.value){await nextTick();metricPanel.value?.beginNew(value as Metric);}}
function toggleAdding(){
  const opening=tab.value==='history'||!adding.value;
  if(opening)newEmail.value=false;
  if(tab.value==='history')tab.value='items';
  adding.value=opening;
  if(!opening)metricPanel.value?.closeEditor();
}
const newTarget = ref<string | number | boolean | null>(null);
const newSeverity = ref<string | number | boolean | null>("warning");
const newEmail = ref(false);
const pendingNode=(rule:AlertRule)=>rule.kind==='node_offline'&&nodes.value.some(n=>String(n.id)===rule.target&&n.status==='pending');
const submitting = ref(false);
const wgMode=ref("discovered");
const wgSource=ref("");
const wgInterface=ref("");
const wgTarget=ref("");
const manualWG=computed(()=>newKind.value==="wg_link"&&wgMode.value==="manual");
const targetReady=computed(()=>manualWG.value ? !!wgSource.value&&!!wgInterface.value&&!!wgTarget.value : newTarget.value!=null);
const wgReason=(reason?:string|null)=>({agent_upgrade_required:'源 agent 需升级后才会下发手动探测',kernel_route_unverified:'本机路由或源地址未核实',missing_or_changed_discovery:'发现报告缺失、过期或身份/归属已变更',missing_or_expired_probe:'等待新鲜探测结果',probe_budget_exhausted:'本轮探测预算不足',ping_unavailable:'agent 不支持或缺少 ping'}[reason||'']||'');
const wgHealth=(health?:string)=>({ok:"可达",degraded:"存在丢包",failed:"无回复",unknown:"未知"}[health||"unknown"]);

// 删除二次确认（破坏性操作）
const confirmDelete = ref<number | null>(null);

const KINDS: { value: AddKind; label: string; desc: string }[] = [
  { value: "node_offline", label: "节点上报中断", desc: "超过 2 分钟未收到上报" },
  { value: "monitor_down", label: "监控项异常", desc: "探测连续失败" },
  { value: "wg_link", label: "WG 链路中断", desc: "任一有效方向失败；消失/过期为未知" },
  {value:"cpu",label:"系统指标",desc:"CPU、内存与磁盘使用率"},
  {value:"network.rate",label:"带宽 / 速率",desc:"瞬时速率或明确配置的容量利用率"},
  {value:"network.volume",label:"累计流量",desc:"明确总量、接口与固定日期窗口"},
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
  if (metricKind.value || !targetReady.value || submitting.value) return;
  submitting.value = true;
  error.value = "";
  try {
    const target = manualWG.value ? "" : String(newTarget.value);
    const wg_manual=manualWG.value?{node_id:Number(wgSource.value),interface:wgInterface.value,target:wgTarget.value}:undefined;
    await createRule({
      kind: newKind.value as AlertRule["kind"],
      target,
      wg_manual,
      label: wg_manual?`${nodeName.value(wg_manual.node_id)} · ${wg_manual.interface} → ${wg_manual.target}`:targetLabel(newKind.value, target),
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

const updatingRules = ref(new Set<number>());
async function toggleRule(rule: AlertRule, field: 'enabled' | 'email') {
  if (updatingRules.value.has(rule.id)) return;
  const value = !rule[field];
  updatingRules.value.add(rule.id);
  error.value = '';
  try {
    await patchRule(rule.id, { [field]: value });
    rule[field] = value;
    revision.value++;
  } catch (e) {
    error.value = (e as { detail?: string; message?: string })?.detail || (e as Error)?.message ||
      (field === 'email' ? '更新邮件设置失败喵~' : '更新告警状态失败喵~');
  } finally { updatingRules.value.delete(rule.id); }
}
function toggleEnabled(rule: AlertRule) { return toggleRule(rule, 'enabled'); }
function toggleEmail(rule: AlertRule) { return toggleRule(rule, 'email'); }

async function removeRule(rule: AlertRule) {
  if (confirmDelete.value !== rule.id) {
    confirmDelete.value = rule.id;
    setTimeout(() => { if (confirmDelete.value === rule.id) confirmDelete.value = null; }, 3000);
    return;
  }
  confirmDelete.value = null;
  try{await deleteRule(rule.id);await reload();}catch{error.value="删除失败，历史仍保留，请重试";}
}

async function reload() {
  try {
    rules.value = await listRules();
    error.value = "";
    revision.value++;
  } catch (e) { error.value = (e as { detail?: string })?.detail || "告警规则刷新失败，已保留上次结果喵~"; throw e; }
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
        <p class="sub">新节点自动添加上报中断告警；站内提醒开启，邮件默认关闭。</p>
        <HelpHint label="节点上报中断说明">首次上报后开始判定，超过 2 分钟未收到上报时提醒。站内通知开启，邮件需手动开启且只影响后续事件。新心跳确认恢复；停用、删除或已读不代表恢复，停用或删除后不会自动重建。中心完全停止时无法自发告警。</HelpHint>
      </div>
      <button class="add-btn" @click="toggleAdding">
        <Icon :name="adding ? 'x' : 'plus'" :size="14" /> {{ tab==='history' ? '添加告警' : adding ? '取消' : '添加告警' }}
      </button>
    </header>

    <nav class="alert-tabs" aria-label="告警页面"><button :class="{active:tab==='items'}" @click="tab='items'">告警项</button><button :class="{active:tab==='history'}" @click="tab='history'">告警记录</button></nav>
    <div v-show="tab==='items'">
    <AlertIncidentList mode="current" :revision="revision" />
    <details class="rule-management" :open="adding"><summary>规则管理与添加 <span>（删除规则保留历史，不代表恢复）</span></summary>
    <!-- 添加面板 -->
    <Transition name="pop">
      <div v-if="adding" class="add-panel">
        <div class="kind-cards">
          <button
            v-for="k in KINDS" :key="k.value"
            :aria-label="k.label" class="kind-card" :class="{ active: newKind === k.value }"
            @click="chooseKind(k.value)"
          >
            <span class="kc-label">{{ k.label }}</span>
            <span class="kc-desc">{{ k.desc }}</span>
          </button>
        </div>
        <div v-if="!metricKind" class="add-row">
          <label v-if="newKind==='wg_link'" class="wg-field">目标来源<select v-model="wgMode" aria-label="WG 目标来源"><option value="discovered">已发现链路</option><option value="manual">手动单向端点</option></select></label>
          <template v-if="manualWG">
            <label class="wg-field">源节点<select v-model="wgSource" aria-label="WG 源节点"><option value="">请选择</option><option v-for="n in nodes.filter(n=>n.status!=='removed')" :key="n.id" :value="String(n.id)">{{ n.name }}</option></select></label>
            <label class="wg-field">本地 WG 接口<input v-model="wgInterface" aria-label="本地 WG 接口" maxlength="15" placeholder="实际接口名称" /></label>
            <label class="wg-field">目标 WG IPv4<input v-model="wgTarget" aria-label="目标 WG IPv4" maxlength="15" placeholder="私网 IPv4" /></label>
          </template>
          <Dropdown v-else v-model="newTarget" :options="targetOptions" />
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
          <button class="submit-btn" :disabled="!targetReady || submitting" @click="submit">
            {{ submitting ? "添加中…" : "添加" }}
          </button>
        </div>
        <HelpHint v-if="newKind==='wg_link'" label="WireGuard 链路规则说明">发现候选不会自动新增规则。已发现链路任一有效方向失败可触发；手动端点仅判断所选单向。消失、过期或采集失败为未知，不触发也不恢复，不静默重绑。手动端点仅支持私网 IPv4、已有 WG 接口及其唯一 AllowedIPs 路由；不修改宿主网络。更换端点请删除后重新添加，旧历史保留。</HelpHint>
        <div v-if="!metricKind&&!manualWG&&!targetOptions.length" class="hint">这个类型下没有可添加的目标了（可能都已加过）喵~</div>
      </div>
    </Transition>

    <MetricAlertsPanel ref="metricPanel" :nodes="nodes" embedded @changed="revision++" />
    <div v-if="error" class="error" role="alert">{{ error }}</div>
    <div v-if="loading" class="hint">加载中…</div>

    <!-- 规则列表 -->
    <div v-else-if="!rules.length && !adding" class="empty">
      还没有告警规则。点右上角「添加告警」，挑一个想盯的目标喵~
    </div>

    <div v-for="rule in rules" :key="rule.id" class="rule" :class="{ off: !rule.enabled }">
      <span class="state-dot" :class="rule.enabled ? (rule.state==='firing'?'firing':pendingNode(rule)||rule.wg_observation?.health==='unknown'?'unknown':rule.state) : 'off'" :title="rule.enabled ? (rule.state === 'firing' ? '正在告警' : pendingNode(rule) ? '等待首次上报' : '未触发')+(rule.wg_observation?.health==='unknown'?' · 当前观测未知':'') : '已停用'" />
      <div class="rule-main">
        <div class="rule-title">
          <span class="rule-label">{{ rule.label || targetLabel(rule.kind, rule.target) }}</span>
          <span class="tag">{{ KIND_LABELS[rule.kind] }}</span>
          <span class="tag sev" :class="rule.severity">{{ rule.severity === "critical" ? "严重" : "普通" }}</span>
        </div>
        <div v-if="rule.wg_manual" class="rule-meta">手动单向 · {{ nodeName(rule.wg_manual.node_id) }} / {{ rule.wg_manual.interface }} → {{ rule.wg_manual.target }} · {{ wgHealth(rule.wg_observation?.health) }} · 探测时间 {{ rule.wg_observation?.checked_at ? new Date(rule.wg_observation.checked_at).toLocaleString() : "暂无" }}<span v-if="rule.wg_observation?.health==='unknown'">（{{ wgReason(rule.wg_observation?.reason) }}；未知不代表恢复）</span></div>
        <div class="rule-meta">
          <template v-if="rule.kind==='node_offline'">{{ pendingNode(rule) ? '等待首次上报 · ' : '' }}超过 120 秒未上报触发</template>
          <template v-else>连续 {{ rule.debounce }} 次异常触发</template>
          · {{ rule.repeat_minutes===0 ? '不重复提醒' : `持续异常每 ${rule.repeat_minutes} 分钟提醒` }}
          <template v-if="rule.state === 'firing' && rule.message"> · {{ rule.message }}</template>
        </div>
      </div>
      <div class="rule-ops">
        <button class="mini" :disabled="updatingRules.has(rule.id)" :class="{ on: rule.email }" title="邮件提醒" @click="toggleEmail(rule)">
          <Icon name="bell" :size="13" /> 邮件{{ rule.email ? "开" : "关" }}
        </button>
        <button class="mini" :disabled="updatingRules.has(rule.id)" :class="{ on: rule.enabled }" @click="toggleEnabled(rule)">
          {{ rule.enabled ? "已启用" : "已停用" }}
        </button>
        <button
          class="mini danger" :disabled="updatingRules.has(rule.id)" :class="{ confirm: confirmDelete === rule.id }"
          @click="removeRule(rule)"
        >
          {{ confirmDelete === rule.id ? "确认删除？" : "删除" }}
        </button>
      </div>
    </div>

    </details>
    <AlertIncidentList mode="recent" :revision="revision" />
    </div>
    <AlertIncidentList v-show="tab==='history'" mode="history" :nodes="nodes" :revision="revision" />
    <AlertIncidentDetail v-if="incidentId" :id="incidentId" @close="closeIncident" />
  </div>
</template>

<style scoped>
.alerts-view {box-sizing:border-box;flex:1;width:100%;min-width:0;min-height:0;height:100%;overflow-y:auto;padding:22px 26px; }
.alert-tabs{display:flex;gap:8px;margin:18px 0 24px}.alert-tabs button{font:inherit;min-height:40px;padding:7px 14px;background:var(--bg-panel);border:1px solid #ffffff25;border-radius:8px;color:var(--text-lo);cursor:pointer}.alert-tabs .active{color:#b2dfce;border-color:#9bcbb680;background:#9bcbb60a}.rule-management{margin-bottom:24px;border:1px solid #ffffff1c;border-radius:10px;padding:14px}.rule-management summary{cursor:pointer;font-size:14px;padding:4px 0 14px}.rule-management summary span{font-size:12px;color:var(--text-lo)}button:focus-visible,summary:focus-visible{outline:2px solid #9bcbb6;outline-offset:3px}

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
.wg-field{display:flex;flex-direction:column;gap:5px;font-size:12px;color:var(--text-lo);min-width:0;flex:0 1 180px}.wg-field input,.wg-field select{box-sizing:border-box;min-width:0;width:100%;min-height:38px;padding:7px 9px;font:inherit;color:var(--text-hi);background:var(--bg-base);border:1px solid var(--accent-dim);border-radius:var(--radius-sm)}.rule-meta{overflow-wrap:anywhere}
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
.state-dot.off,.state-dot.unknown { background: #5c6474; }
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
  .alerts-view{padding:18px 14px} .head{flex-wrap:wrap} .kind-card{min-width:0;flex:1 1 140px} button{min-height:44px}
  .rule { flex-wrap: wrap; }
  .rule-ops { width: 100%; }
}
</style>
