<script setup lang="ts">
// 设置页：标签页切换（我的资料 / 管理员设置[admin] / 其他），页内切换不新开
import { ref, computed, onMounted } from "vue";
import { auth, isAdmin, currentAvatar, logout } from "../home/auth";
import { useRouter } from "vue-router";
import AvatarCropper from "./AvatarCropper.vue";

const router = useRouter();

/* ---------- 标签页 ---------- */
const tab = ref<"profile" | "admin" | "misc">("profile");
const tabs = computed(() => {
  const t = [{ key: "profile", label: "我的资料" }];
  if (isAdmin.value) t.push({ key: "admin", label: "管理员设置" });
  t.push({ key: "misc", label: "其他" });
  return t;
});

/* ---------- 我的资料 ---------- */
const editingName = ref(false);
const nameDraft = ref("");
const profileMsg = ref("");
const cropperOpen = ref(false);
const pwdOpen = ref(false);
const mailOpen = ref(false);
const mailDraft = ref("");
const mailMsg = ref("");
const mailStage = ref<"input" | "code">("input"); // 邮箱浮窗两阶段
const mailCode = ref("");
const emailSvc = ref({ ready: true, configured: true, enabled: true });

async function checkEmailService() {
  try {
    const r = await fetch("/auth/email-service");
    emailSvc.value = await r.json();
  } catch { /* 静默 */ }
}

const oldPwd = ref("");
const newPwd = ref("");
const pwdMsg = ref("");

/* ---------- 头像历史（近 5 个） ---------- */
const avatarHistory = ref<string[]>([]);
async function loadAvatarHistory() {
  const r = await fetch("/auth/avatars");
  if (r.ok) avatarHistory.value = await r.json();
}
async function pickAvatar(url: string) {
  const r = await fetch("/auth/avatar-pick", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (r.ok) {
    auth.me = await r.json();
    profileMsg.value = "换回老头像啦";
    loadAvatarHistory();
  }
}

async function saveName() {
  profileMsg.value = "";
  const name = nameDraft.value.trim();
  if (!name) return;
  const r = await fetch("/auth/me", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_name: name }),
  });
  if (r.ok) {
    auth.me = await r.json();
    editingName.value = false;
    profileMsg.value = "昵称改好啦";
  }
}

async function saveMail() {
  // 暂不验证：直接存（未验证状态）
  mailMsg.value = "";
  const r = await fetch("/auth/me", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: mailDraft.value.trim() }),
  });
  const d = await r.json();
  if (r.ok) {
    auth.me = d;
    mailOpen.value = false;
    mailStage.value = "input";
    profileMsg.value = "邮箱存好啦（未验证）";
  } else {
    mailMsg.value = d.detail ?? "失败";
  }
}

async function sendMailCode() {
  mailMsg.value = "";
  if (!emailSvc.value.ready) {
    // 分三种情况给精准提示
    if (isAdmin.value) {
      if (emailSvc.value.configured && !emailSvc.value.enabled) {
        mailMsg.value = "邮箱服务的开关没开喵~ 去「管理员设置 → Stella 邮箱服务」把开关打开就能用";
      } else {
        mailMsg.value = "邮箱服务还没配置喵~ 你是管理员——去「管理员设置 → Stella 邮箱服务」填上域名/密钥就能用";
      }
    } else {
      mailMsg.value = "邮箱服务还没配置喵~ 戳管理员让他在「管理员设置 → Stella 邮箱服务」里配置";
    }
    return;
  }
  const r = await fetch("/auth/email/send-code", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: mailDraft.value.trim() }),
  });
  const d = await r.json();
  if (r.ok) {
    mailStage.value = "code";
    mailMsg.value = "验证码飞过去啦，10 分钟内有效喵~";
  } else {
    mailMsg.value = d.detail ?? "发送失败";
  }
}

async function verifyMail() {
  mailMsg.value = "";
  const r = await fetch("/auth/email/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: mailDraft.value.trim(), code: mailCode.value.trim() }),
  });
  const d = await r.json();
  if (r.ok) {
    auth.me = d;
    mailOpen.value = false;
    mailStage.value = "input";
    mailCode.value = "";
    profileMsg.value = "邮箱验证通过 ✅";
  } else {
    mailMsg.value = d.detail ?? "验证失败";
  }
}

async function resendBindCode() {
  mailMsg.value = "";
  const r = await fetch("/auth/email/resend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: mailDraft.value.trim(), purpose: "bind" }),
  });
  const d = await r.json();
  if (r.ok) {
    mailMsg.value = "新验证码飞过去啦（旧码作废）";
  } else {
    mailMsg.value = d.detail ?? "重发失败";
  }
}

async function changePwd() {
  pwdMsg.value = "";
  const r = await fetch("/auth/password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ old_password: oldPwd.value, new_password: newPwd.value }),
  });
  const d = await r.json();
  if (r.ok) {
    pwdMsg.value = d.hint ?? "已改";
    oldPwd.value = "";
    newPwd.value = "";
    setTimeout(() => { logout(); router.push("/login"); }, 1200);
  } else {
    pwdMsg.value = d.detail ?? "失败";
  }
}

function onAvatarDone(url: string) {
  if (auth.me) auth.me.avatar_url = url;
  profileMsg.value = "头像换好啦";
  loadAvatarHistory();
}

function openMailEditor() {
  mailDraft.value = auth.me?.email ?? "";
  mailStage.value = "input";
  mailMsg.value = "";
  mailCode.value = "";
  mailOpen.value = true;
  checkEmailService();
}

async function doLogout() {
  await logout();
  router.push("/login");
}

/* ---------- 登录记录 ---------- */
interface SessionRow {
  id: string; device: string; ip: string; remember: boolean;
  created_at: string; last_seen: string; current: boolean;
  owner: string; mine: boolean;
}
const sessions = ref<SessionRow[]>([]);
const sessMsg = ref("");
// 分组：当前账号 vs 其他账号（admin 可见其他）
const mineSessions = computed(() => sessions.value.filter((s) => s.mine));
const otherSessions = computed(() => sessions.value.filter((s) => !s.mine));

async function loadSessions() {
  const r = await fetch("/auth/sessions");
  if (r.ok) sessions.value = await r.json();
}

async function revoke(s: SessionRow) {
  if (!confirm(`踢下线「${s.owner} 的 ${s.device} · ${s.ip}」？`)) return;
  const r = await fetch(`/auth/sessions/${s.id}`, { method: "DELETE" });
  if (r.ok) {
    sessMsg.value = "已踢下线";
    loadSessions();
  } else {
    sessMsg.value = (await r.json()).detail ?? "失败";
  }
}

/* ---------- 管理员设置 ---------- */
interface UserRow { id: string; username: string; display_name: string; is_admin: boolean; }
const users = ref<UserRow[]>([]);
interface InviteRow { token: string; created_at: string; used: boolean; expired: boolean; }
const invites = ref<InviteRow[]>([]);
const inviteMsg = ref("");

async function loadUsers() {
  const r = await fetch("/users/?limit=1000");
  if (r.ok) users.value = await r.json();
}
async function loadInvites() {
  const r = await fetch("/auth/invites");
  if (r.ok) invites.value = await r.json();
}
async function createInvite() {
  inviteMsg.value = "";
  const r = await fetch("/auth/invites", { method: "POST" });
  if (!r.ok) { inviteMsg.value = "生成失败：" + r.status; return; }
  const d = await r.json();
  const full = location.origin + d.url;
  try {
    await navigator.clipboard.writeText(full);
    inviteMsg.value = `链接已复制（30 分钟内有效）：${full}`;
  } catch {
    inviteMsg.value = `链接（30 分钟内有效）：${full}`;
  }
  loadInvites();
}

/* ---------- Stella 邮箱服务（admin） ---------- */
const emailCfg = ref({ host: "", port: 465, username: "", password: "", from_name: "StellaHaven 港务局", enabled: false });
const emailMsg = ref("");
const testTo = ref("");
const testMsg = ref("");

async function loadEmailCfg() {
  const r = await fetch("/admin/email/config");
  if (r.ok) emailCfg.value = await r.json();
}
async function saveEmailCfg() {
  emailMsg.value = "";
  const r = await fetch("/admin/email/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(emailCfg.value),
  });
  emailMsg.value = r.ok ? "配置已保存" : "保存失败：" + r.status;
}
async function sendTestMail() {
  testMsg.value = "";
  if (!testTo.value.includes("@")) { testMsg.value = "先填收件邮箱喵~"; return; }
  const r = await fetch("/admin/email/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to: testTo.value }),
  });
  const d = await r.json();
  testMsg.value = r.ok ? `已发往 ${d.to}，去收件箱看看喵~` : (d.detail ?? "发送失败");
}

function fmtTime(iso: string) {
  return new Date(iso).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

onMounted(() => {
  nameDraft.value = auth.me?.display_name ?? "";
  mailDraft.value = auth.me?.email ?? "";
  loadSessions();
  loadAvatarHistory();
  if (isAdmin.value) { loadUsers(); loadInvites(); loadEmailCfg(); }
});
</script>

<template>
  <div class="page">
    <div class="wrap">
      <h1 class="h1">设置</h1>

      <!-- 标签页 -->
      <div class="tabs">
        <button
          v-for="t in tabs"
          :key="t.key"
          class="tab"
          :class="{ on: tab === t.key }"
          @click="tab = t.key as any"
        >{{ t.label }}</button>
      </div>

      <!-- ═══ 我的资料 ═══ -->
      <template v-if="tab === 'profile'">
        <section class="card">
          <div class="me-row">
            <button class="me-avatar-btn" title="点我换头像" @click="cropperOpen = true">
              <img class="me-avatar" :src="currentAvatar" alt="头像" />
              <span class="me-avatar-hint">✎</span>
            </button>
            <div class="me-info">
              <div v-if="!editingName" class="me-name-row">
                <span class="me-name">{{ auth.me?.display_name }}</span>
                <button class="mini" @click="editingName = true">改昵称</button>
              </div>
              <div v-else class="me-name-row">
                <input v-model="nameDraft" class="input name-input" @keydown.enter="saveName" />
                <button class="mini" @click="saveName">存</button>
                <button class="mini" @click="editingName = false">取消</button>
              </div>
              <div class="me-sub">@{{ auth.me?.username }} · {{ auth.me?.is_admin ? "管理员" : "成员" }}</div>
              <div class="me-sub">
                📮 {{ auth.me?.email || "未绑定邮箱" }}
                <span v-if="auth.me?.email" class="mail-badge" :class="auth.me?.email_verified ? 'ok' : 'pending'">
                  {{ auth.me?.email_verified ? "已验证" : "未验证" }}
                </span>
              </div>
            </div>
          </div>
          <!-- 按钮行：绑定/改邮箱 / 修改密码 / 退出登录 -->
          <div class="btn-row">
            <button class="btn ghost" @click="openMailEditor">{{ auth.me?.email ? "修改邮箱" : "绑定邮箱" }}</button>
            <button class="btn ghost" @click="pwdOpen = true">修改密码</button>
            <button class="btn ghost" @click="doLogout">退出登录</button>
          </div>
          <div v-if="profileMsg" class="ok-msg">{{ profileMsg }}</div>

          <!-- 头像历史（近 5 个，点选换回） -->
          <div v-if="avatarHistory.length" class="avatar-history">
            <div class="ah-label">近期头像（点选换回）</div>
            <div class="ah-row">
              <img
                v-for="u in avatarHistory"
                :key="u"
                :src="u"
                class="ah-thumb"
                :class="{ on: u === auth.me?.avatar_url }"
                @click="pickAvatar(u)"
              />
            </div>
          </div>
        </section>

        <section class="card">
          <div class="sec-t">登录记录 <span class="sec-sub">{{ isAdmin ? "管理员可看全部、踢任意" : "只能踢自己的" }}</span></div>
          <div v-if="sessMsg" class="ok-msg">{{ sessMsg }}</div>
          <template v-if="mineSessions.length">
            <div class="sess-group">当前账号</div>
            <div v-for="s in mineSessions" :key="s.id" class="sess-row">
              <div class="sess-main">
                <span class="sess-device">{{ s.device }}</span>
                <span v-if="s.current" class="cur">本机</span>
                <span v-if="s.remember" class="rem">记住我</span>
              </div>
              <div class="sess-sub">{{ s.ip || "局域网" }} · 登录 {{ fmtTime(s.created_at) }} · 活跃 {{ fmtTime(s.last_seen) }}</div>
              <button v-if="!s.current" class="mini danger" @click="revoke(s)">踢下线</button>
            </div>
          </template>
          <template v-if="otherSessions.length">
            <div class="sess-group">其他账号</div>
            <div v-for="s in otherSessions" :key="s.id" class="sess-row">
              <div class="sess-main">
                <span class="sess-device">{{ s.device }}</span>
                <span class="rem">{{ s.owner }}</span>
              </div>
              <div class="sess-sub">{{ s.ip || "局域网" }} · 登录 {{ fmtTime(s.created_at) }} · 活跃 {{ fmtTime(s.last_seen) }}</div>
              <button class="mini danger" @click="revoke(s)">踢下线</button>
            </div>
          </template>
          <div v-if="!sessions.length" class="hint">暂无会话</div>
        </section>
      </template>

      <!-- ═══ 管理员设置 ═══ -->
      <template v-else-if="tab === 'admin'">
        <section class="card">
          <div class="sec-t">用户列表</div>
          <div v-for="u in users" :key="u.id" class="user-row">
            <span class="u-name">{{ u.display_name }}</span>
            <span class="u-sub">@{{ u.username }}</span>
            <span v-if="u.is_admin" class="u-admin">admin</span>
          </div>
        </section>

        <section class="card">
          <div class="sec-t">邀请新用户</div>
          <div class="hint">注册通道已关闭——新用户只能靠邀请链接：30 分钟有效、一个链接只进一个人。</div>
          <button class="btn" style="margin-top:10px" @click="createInvite">生成注册链接</button>
          <div v-if="inviteMsg" class="ok-msg">{{ inviteMsg }}</div>
          <div v-for="i in invites" :key="i.token" class="sess-row">
            <div class="sess-main">
              <span class="sess-device">/invite/{{ i.token.slice(0, 8) }}…</span>
              <span v-if="i.used" class="cur">已使用</span>
              <span v-else-if="i.expired" class="rem">已过期</span>
              <span v-else class="cur">可用</span>
            </div>
            <div class="sess-sub">{{ fmtTime(i.created_at) }} 生成</div>
          </div>
        </section>

        <section class="card">
          <div class="sec-t">Stella 邮箱服务 <span class="sec-sub">网站外发邮件（重置密码验证码等）</span></div>
          <div class="field-row">
            <span class="f-label">开关</span>
            <button class="switch" :class="{ on: emailCfg.enabled }" role="switch" @click="emailCfg.enabled = !emailCfg.enabled"><i /></button>
            <span class="f-hint">开启后启用邮箱认证登录 / 忘记密码</span>
          </div>
          <div class="field-row"><span class="f-label">域名</span><input v-model="emailCfg.host" class="input" placeholder="smtp.example.com" /></div>
          <div class="field-row"><span class="f-label">端口</span><input v-model.number="emailCfg.port" type="number" class="input" placeholder="465" /></div>
          <div class="field-row"><span class="f-label">账号</span><input v-model="emailCfg.username" class="input" placeholder="noreply@xiya.live" /></div>
          <div class="field-row"><span class="f-label">密钥</span><input v-model="emailCfg.password" type="password" class="input" placeholder="SMTP 密码 / 授权码" /></div>
          <div class="field-row"><span class="f-label">签名</span><input v-model="emailCfg.from_name" class="input" placeholder="StellaHaven 港务局" /></div>
          <button class="btn" @click="saveEmailCfg">保存配置</button>
          <div v-if="emailMsg" class="ok-msg">{{ emailMsg }}</div>
          <div class="mail-test">
            <input v-model="testTo" class="input" placeholder="测试收件邮箱" />
            <button class="btn" @click="sendTestMail">发送测试邮件</button>
          </div>
          <div v-if="testMsg" class="ok-msg">{{ testMsg }}</div>
        </section>
      </template>

      <!-- ═══ 其他 ═══ -->
      <template v-else>
        <section class="card">
          <div class="sec-t">其他</div>
          <div class="hint">通用设置以后搬来这里。现在先去主页齿轮里玩主题和背景图喵~</div>
        </section>
      </template>
    </div>

    <AvatarCropper v-if="cropperOpen" @close="cropperOpen = false" @done="onAvatarDone" />

    <!-- 修改密码浮窗 -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="pwdOpen" class="mini-mask" @click.self="pwdOpen = false">
          <div class="mini-pop">
            <div class="mp-t">修改密码</div>
            <input v-model="oldPwd" type="password" class="input" placeholder="原密码" />
            <input v-model="newPwd" type="password" class="input" placeholder="新密码（至少 6 位）" style="margin-top:10px" />
            <div v-if="pwdMsg" class="ok-msg">{{ pwdMsg }}</div>
            <div class="mp-actions">
              <button class="btn ghost" @click="pwdOpen = false">取消</button>
              <button class="btn" :disabled="!oldPwd || !newPwd" @click="changePwd">改</button>
            </div>
            <div class="hint">改完全部会话下线，要重新登录一次。</div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 绑定/改邮箱浮窗：暂不验证 or 发验证码两阶段 -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="mailOpen" class="mini-mask" @click.self="mailOpen = false">
          <div class="mini-pop">
            <div class="mp-t">{{ auth.me?.email ? "修改邮箱" : "绑定邮箱" }}</div>
            <template v-if="mailStage === 'input'">
              <input v-model="mailDraft" class="input" placeholder="you@example.com" @keydown.enter="sendMailCode" />
              <div v-if="mailMsg" class="ok-msg warn">{{ mailMsg }}</div>
              <div class="mp-actions">
                <button class="btn ghost" @click="saveMail">暂不验证</button>
                <button class="btn" @click="sendMailCode">发送验证码</button>
              </div>
            </template>
            <template v-else>
              <div class="hint" style="margin:0 0 10px">验证码已发往 {{ mailDraft }}，10 分钟有效喵~</div>
              <input v-model="mailCode" class="input" placeholder="6 位验证码" maxlength="6" @keydown.enter="verifyMail" />
              <div v-if="mailMsg" class="ok-msg warn">{{ mailMsg }}</div>
              <div class="mp-actions">
                <button class="btn ghost" @click="mailStage = 'input'">返回</button>
                <button class="btn ghost" @click="resendBindCode">重新发送</button>
                <button class="btn" :disabled="mailCode.length !== 6" @click="verifyMail">完成验证</button>
              </div>
            </template>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.page { height: 100%; overflow-y: auto; padding: 40px 24px 60px; }
.wrap { max-width: 640px; margin: 0 auto; }
.h1 { font-size: 24px; font-weight: 600; color: var(--text-hi); letter-spacing: 3px; margin-bottom: 20px; }

.tabs { display: flex; gap: 6px; margin-bottom: 18px; border-bottom: 1px solid rgba(255,255,255,0.07); }
.tab {
  padding: 9px 18px;
  border: none;
  background: transparent;
  color: var(--text-lo);
  font-size: 13.5px;
  font-family: inherit;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition: all 200ms;
  letter-spacing: 1px;
}
.tab:hover { color: var(--text-hi); }
.tab.on { color: var(--accent); border-bottom-color: var(--accent); }

.card {
  background: color-mix(in srgb, var(--bg-panel) 80%, transparent);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 16px;
  padding: 20px 22px;
  margin-bottom: 18px;
}
.sec-t { font-size: 14.5px; font-weight: 600; color: var(--text-hi); letter-spacing: 1.5px; margin-bottom: 14px; }
.sec-sub { font-size: 11.5px; color: var(--text-faint); font-weight: 400; margin-left: 8px; }
.me-row { display: flex; align-items: center; gap: 14px; }
.me-avatar-btn {
  position: relative;
  width: 52px; height: 52px;
  border-radius: 50%;
  border: 2px solid var(--accent-dim);
  padding: 0;
  cursor: pointer;
  overflow: hidden;
  background: none;
  flex-shrink: 0;
}
.me-avatar { width: 100%; height: 100%; object-fit: cover; display: block; }
.me-avatar-hint {
  position: absolute; inset: 0;
  display: grid; place-items: center;
  background: rgba(10, 14, 20, 0.45);
  color: #fff; font-size: 15px;
  opacity: 0; transition: opacity 180ms;
}
.me-avatar-btn:hover .me-avatar-hint { opacity: 1; }
.me-info { flex: 1; min-width: 0; }
.me-name-row { display: flex; align-items: center; gap: 8px; }
.me-name { font-size: 16px; font-weight: 600; color: var(--text-hi); }
.me-sub { font-size: 12px; color: var(--text-lo); margin-top: 3px; }
.hint { margin-top: 12px; font-size: 11.5px; color: var(--text-faint); line-height: 1.6; }
.ok-msg { margin: 10px 0 0; font-size: 12.5px; color: #a8d8b0; }
.field { margin-bottom: 10px; }
.input {
  width: 100%; padding: 9px 12px; border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-hi); font-size: 13px; font-family: inherit; outline: none;
}
.input:focus { border-color: var(--accent-dim); }
.name-input { width: 160px; }
.sess-row {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px; border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
  margin-bottom: 8px;
}
.sess-main { display: flex; align-items: center; gap: 8px; }
.sess-device { font-size: 13.5px; color: var(--text-hi); }
.cur { font-size: 10px; padding: 1px 8px; border-radius: 999px; background: color-mix(in srgb, var(--accent) 20%, transparent); color: var(--accent); }
.rem { font-size: 10px; padding: 1px 8px; border-radius: 999px; background: rgba(255, 255, 255, 0.07); color: var(--text-lo); }
.sess-sub { flex: 1; font-size: 11.5px; color: var(--text-faint); }
.mini {
  padding: 4px 12px; border-radius: 8px; border: none;
  font-size: 11.5px; cursor: pointer; font-family: inherit;
  background: rgba(255, 255, 255, 0.06); color: var(--text-lo);
}
.mini:hover { color: var(--text-hi); }
.mini.danger:hover { background: rgba(150, 60, 75, 0.5); color: #f0c8d0; }
.user-row { display: flex; align-items: baseline; gap: 10px; padding: 8px 4px; }
.u-name { font-size: 14px; color: var(--text-hi); }
.u-sub { font-size: 11.5px; color: var(--text-faint); }
.u-admin { font-size: 10px; padding: 1px 8px; border-radius: 999px; background: rgba(232, 160, 191, 0.15); color: #e8a0bf; }
.btn {
  padding: 8px 18px; border-radius: 10px; border: none;
  background: var(--accent); color: #141824;
  font-size: 13px; font-weight: 600; cursor: pointer; font-family: inherit;
}
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn.ghost { background: transparent; color: var(--text-lo); border: 1px solid rgba(255, 255, 255, 0.12); font-weight: 400; }
.btn.ghost:hover { color: var(--text-hi); }
.btn-row { display: flex; gap: 10px; margin-top: 16px; }
.avatar-history { margin-top: 16px; }
.ah-label { font-size: 11.5px; color: var(--text-faint); letter-spacing: 1px; margin-bottom: 8px; }
.ah-row { display: flex; gap: 8px; }
.ah-thumb {
  width: 40px; height: 40px; border-radius: 50%;
  object-fit: cover; cursor: pointer;
  border: 2px solid transparent;
  opacity: 0.65;
  transition: all 180ms;
}
.ah-thumb:hover { opacity: 1; transform: scale(1.08); }
.ah-thumb.on { border-color: var(--accent); opacity: 1; }
.sess-group {
  font-size: 11px; color: var(--text-faint); letter-spacing: 2px;
  margin: 10px 0 8px;
}
.sess-group:first-of-type { margin-top: 0; }
.field-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.field-row .f-label { width: 44px; flex-shrink: 0; font-size: 12.5px; color: var(--text-lo); }
.f-hint { font-size: 11.5px; color: var(--text-faint); }
.mail-test { display: flex; gap: 10px; margin-top: 14px; }
.switch {
  width: 40px; height: 22px; border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.08);
  cursor: pointer; position: relative; transition: all 220ms; padding: 0;
  flex-shrink: 0;
}
.switch i {
  position: absolute; left: 2px; top: 2px;
  width: 16px; height: 16px; border-radius: 50%;
  background: var(--text-lo);
  transition: all 220ms cubic-bezier(0.22, 1, 0.36, 1);
}
.switch.on { background: color-mix(in srgb, var(--accent) 55%, transparent); border-color: var(--accent-dim); }
.switch.on i { left: 20px; background: #fff; }
.mini-mask {
  position: fixed; inset: 0; z-index: 135;
  background: rgba(6, 10, 16, 0.5);
  display: flex; align-items: center; justify-content: center;
}
.mini-pop {
  width: 320px;
  background: color-mix(in srgb, var(--bg-panel) 94%, transparent);
  backdrop-filter: var(--blur);
  border: 1px solid rgba(255, 255, 255, 0.09);
  border-radius: 16px;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.5);
  padding: 20px 22px;
}
.mail-badge {
  font-size: 10px;
  padding: 1px 8px;
  border-radius: 999px;
  margin-left: 4px;
  vertical-align: 1px;
}
.mail-badge.pending { color: #e89aa8; background: rgba(220, 120, 140, 0.14); border: 1px solid rgba(220, 120, 140, 0.3); }
.mail-badge.ok { color: #9ed8b0; background: rgba(130, 210, 150, 0.12); border: 1px solid rgba(130, 210, 150, 0.3); }
.ok-msg.warn { color: #e8c9a0; }
.mp-t { font-size: 14px; font-weight: 600; color: var(--text-hi); letter-spacing: 2px; margin-bottom: 12px; }
.mp-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 14px; }
.fade-enter-active, .fade-leave-active { transition: opacity 240ms; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
