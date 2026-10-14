<script setup lang="ts">
// Reused login/initialization form, shown above the current page.
// 形态自动检测：未初始化 → 「还没初始化哦，点击开始喵~」引导进初始化表单；
// 已初始化 → 单用户纯登录；初始化只创建唯一 owner。
import { ref, onMounted, onUnmounted, nextTick, watch } from "vue";
import { login, register, acceptLogin } from "../home/auth";
import {consumeLoginFocus} from "./loginPrompt";
const emit=defineEmits<{success:[];close:[]}>();
const dialog=ref<HTMLElement>();
let previousFocus:HTMLElement|null=null;
const focusFirst=()=>{const input=dialog.value?.querySelector<HTMLElement>('input:not([type="checkbox"]), .submit');(input||dialog.value)?.focus();};
function keyboard(event:KeyboardEvent){
 if(event.key==='Escape'){event.preventDefault();if(!busy.value)emit('close');}
 if(event.key!=='Tab')return;
 const items=Array.from(dialog.value?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), a[href], [tabindex="0"]')||[]);
 const first=items[0],last=items.at(-1);
 if(!first){event.preventDefault();dialog.value?.focus();return;}
 if(event.shiftKey&&(document.activeElement===first||document.activeElement===dialog.value)){event.preventDefault();last?.focus();}
 else if(!event.shiftKey&&(document.activeElement===last||document.activeElement===dialog.value)){event.preventDefault();first.focus();}
}

onUnmounted(()=>{
 const rect=previousFocus?.getBoundingClientRect();
 if(previousFocus!==document.body&&previousFocus!==document.documentElement&&previousFocus?.isConnected&&rect&&rect.width>0&&rect.right>0&&rect.left<innerWidth&&rect.bottom>0&&rect.top<innerHeight)previousFocus.focus();
 else {
  const target=['.hamburger','.account'].map(selector=>document.querySelector<HTMLElement>(selector)).find(el=>{const box=el?.getBoundingClientRect();return box&&box.width>0&&box.right>0&&box.left<innerWidth;});
  target?.focus();
 }
});
const phase = ref<"loading" | "init-guide" | "init-form" | "login" | "forgot" | "forgot-code" | "code-login" | "code-login-verify">("loading");
const emailEnabled = ref(false);
watch(()=>phase.value,async()=>{await nextTick();focusFirst();});

const username = ref("");
const password = ref("");
const displayName = ref("");
const remember = ref(true);
const error = ref("");
const notice = ref("");
const busy = ref(false);

// 忘记密码
const forgotEmail = ref("");
const forgotCode = ref("");
const newPassword = ref("");

// 验证码登录
const codeLoginEmail = ref("");
const codeLoginCode = ref("");

onMounted(async () => {
  previousFocus=consumeLoginFocus()||document.activeElement as HTMLElement;dialog.value?.focus();
  try {
    const r = await formFetch("/auth/status");
    if(!r.ok)throw new Error('status unavailable');
    const s = await r.json();
    emailEnabled.value = !!s.email_enabled;
    phase.value = s.initialized ? "login" : "init-guide";
  } catch {
    error.value = "登录状态加载失败，请关闭后重试";
    phase.value = "login";
  }
});

async function submit() {
  if(busy.value)return;
  error.value = "";
  notice.value = "";
  busy.value = true;
  try {
    const err=phase.value === 'init-form'
      ? await register(username.value,password.value,displayName.value||undefined)
      : await login(username.value,password.value,remember.value);
    if(err)error.value=err;else emit('success');
  } catch {error.value='连接失败，请重试';}
  finally {busy.value=false;}
}

// All existing email/reset phases share the same retryable transport error.
async function formFetch(input:RequestInfo|URL,init?:RequestInit){
 try{return await fetch(input,init);}catch{return new Response(JSON.stringify({detail:'连接失败，请重试'}),{status:503,headers:{'Content-Type':'application/json'}});}
}

async function sendResetCode() {
  error.value = "";
  notice.value = "";
  busy.value = true;
  const r = await formFetch("/auth/forgot", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: forgotEmail.value.trim() }),
  });
  busy.value = false;
  if (r.ok) {
    phase.value = "forgot-code";
    notice.value = "重置码飞过去啦，10 分钟有效喵~（没账号的信箱不会发）";
  } else {
    error.value = (await r.json()).detail ?? "发送失败";
  }
}

async function doReset() {
  error.value = "";
  busy.value = true;
  const r = await formFetch("/auth/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: forgotEmail.value.trim(), code: forgotCode.value.trim(), new_password: newPassword.value }),
  });
  busy.value = false;
  const d = await r.json();
  if (r.ok) {
    phase.value = "login";
    notice.value = d.hint ?? "重置好啦，用新密码登录喵~";
    forgotCode.value = "";
    newPassword.value = "";
  } else {
    error.value = d.detail ?? "重置失败";
  }
}

async function sendLoginCode() {
  error.value = "";
  notice.value = "";
  busy.value = true;
  const r = await formFetch("/auth/login-code/send", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: codeLoginEmail.value.trim() }),
  });
  busy.value = false;
  if (r.ok) {
    phase.value = "code-login-verify";
    notice.value = "登录验证码飞过去啦，10 分钟有效喵~";
  } else {
    error.value = (await r.json()).detail ?? "发送失败";
  }
}

async function doLoginCode() {
  error.value = "";
  busy.value = true;
  const r = await formFetch("/auth/login-code", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: codeLoginEmail.value.trim(), code: codeLoginCode.value.trim(), remember: remember.value }),
  });
  busy.value = false;
  if (r.ok) {
    acceptLogin(await r.json());
    emit("success");
  } else {
    error.value = (await r.json()).detail ?? "登录失败";
  }
}

async function resendCode(email: string, purpose: "login" | "reset") {
  error.value = "";
  notice.value = "";
  busy.value = true;
  const r = await formFetch("/auth/email/resend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, purpose }),
  });
  busy.value = false;
  const d = await r.json();
  if (r.ok) {
    notice.value = "新验证码飞过去啦，10 分钟有效喵~（旧码作废）";
  } else {
    error.value = d.detail ?? "重发失败";
  }
}
</script>

<template>
  <div class="auth" @click.self="!busy && emit('close')">
    <div ref="dialog" class="card" role="dialog" aria-modal="true" aria-label="Stella 登录" tabindex="-1" @keydown="keyboard">
      <button class="close-login" aria-label="关闭登录" :disabled="busy" @click="emit('close')">×</button>
      <div class="logo">✦</div>

      <!-- 加载中 -->
      <template v-if="phase === 'loading'">
        <div class="site">StellaHaven</div>
        <div class="sub">看港口的灯亮没亮…</div>
      </template>

      <!-- 未初始化：引导 -->
      <template v-else-if="phase === 'init-guide'">
        <div class="site"> StellaHaven </div>
        <div class="sub">港湾还没有主人哦</div>
        <div class="init-hint">
          检测到系统还没初始化喵~<br />
          <span>创建唯一账号，日常登录不会直接解锁管理权限。</span>
        </div>
        <button class="submit" @click="phase = 'init-form'">开始初始化</button>
      </template>

      <!-- 初始化表单 -->
      <template v-else-if="phase === 'init-form'">
        <div class="site">创建唯一账号</div>
        <div class="sub">初始化只此一次；登录后在设置中创建独立管理密码。</div>
        <div class="field">
          <span class="f-label">用户名</span>
          <input v-model="username" class="input" autocomplete="username" @keydown.enter="submit" />
        </div>
        <div class="field">
          <span class="f-label">昵称</span>
          <input v-model="displayName" class="input" placeholder="没填就用用户名" @keydown.enter="submit" />
        </div>
        <div class="field">
          <span class="f-label">密码</span>
          <input v-model="password" type="password" class="input" autocomplete="new-password" @keydown.enter="submit" />
        </div>
        <div v-if="error" class="err" role="alert">{{ error }}</div>
        <button class="submit" :disabled="busy" @click="submit">{{ busy ? "…" : "点亮港口" }}</button>
      </template>

      <!-- 纯登录 -->
      <template v-else-if="phase === 'login'">
        <div class="site">欢迎回港</div>
        <div class="sub">StellaHaven 在等你</div>
        <div class="field">
          <span class="f-label">账号</span>
          <input v-model="username" class="input" placeholder="用户名 / 昵称 / 邮箱" autocomplete="username" @keydown.enter="submit" />
        </div>
        <div class="field">
          <span class="f-label">密码</span>
          <input v-model="password" type="password" class="input" autocomplete="current-password" @keydown.enter="submit" />
        </div>
        <div class="row-line">
          <label class="remember">
            <input v-model="remember" type="checkbox" />
            <span>记住我（30 天）</span>
          </label>
          <div class="row-links">
            <a v-if="emailEnabled" class="forgot" role="button" tabindex="0" @keydown.enter="($event.currentTarget as HTMLElement).click()" @keydown.space.prevent="($event.currentTarget as HTMLElement).click()" @click="phase = 'code-login'; error = ''; notice = ''; codeLoginCode = ''">验证码登录</a>
            <a v-if="emailEnabled" class="forgot" role="button" tabindex="0" @keydown.enter="($event.currentTarget as HTMLElement).click()" @keydown.space.prevent="($event.currentTarget as HTMLElement).click()" @click="phase = 'forgot'; error = ''; notice = ''">忘记密码？</a>
          </div>
        </div>
        <div v-if="notice" class="notice">{{ notice }}</div>
        <div v-if="error" class="err" role="alert">{{ error }}</div>
        <button class="submit" :disabled="busy" @click="submit">{{ busy ? "…" : "回港" }}</button>
      </template>

      <!-- 忘记密码：输邮箱发码 -->
      <template v-else-if="phase === 'forgot'">
        <div class="site">忘记密码</div>
        <div class="sub">输你绑定的邮箱，重置码马上飞过去喵~</div>
        <div class="field">
          <span class="f-label">邮箱</span>
          <input v-model="forgotEmail" class="input" placeholder="你验证过的邮箱" @keydown.enter="sendResetCode" />
        </div>
        <div v-if="error" class="err" role="alert">{{ error }}</div>
        <div class="row-btns">
          <button class="submit ghost-btn" @click="phase = 'login'">想起密码了</button>
          <button class="submit" :disabled="busy" @click="sendResetCode">{{ busy ? "…" : "发送重置码" }}</button>
        </div>
      </template>

      <!-- 忘记密码：输码+新密码 -->
      <template v-else-if="phase === 'forgot-code'">
        <div class="site">重置密码</div>
        <div class="sub">码已飞往 {{ forgotEmail }}</div>
        <div class="field">
          <span class="f-label">重置码</span>
          <input v-model="forgotCode" class="input" placeholder="6 位数字" maxlength="6" @keydown.enter="doReset" />
        </div>
        <div class="field">
          <span class="f-label">新密码</span>
          <input v-model="newPassword" type="password" class="input" placeholder="至少 6 位" @keydown.enter="doReset" />
        </div>
        <div v-if="notice" class="notice">{{ notice }}</div>
        <div v-if="error" class="err" role="alert">{{ error }}</div>
        <button class="submit" :disabled="busy || forgotCode.length !== 6" @click="doReset">{{ busy ? "…" : "重置并去登录" }}</button>
        <div class="resend-line">
          <a class="forgot" role="button" tabindex="0" @keydown.enter="($event.currentTarget as HTMLElement).click()" @keydown.space.prevent="($event.currentTarget as HTMLElement).click()" @click="resendCode(forgotEmail, 'reset')">重新发送</a>
        </div>
      </template>

      <!-- 验证码登录：输邮箱发码 -->
      <template v-else-if="phase === 'code-login'">
        <div class="site">验证码登录</div>
        <div class="sub">输你验证过的邮箱，登录码马上飞过去喵~</div>
        <div class="field">
          <span class="f-label">邮箱</span>
          <input v-model="codeLoginEmail" class="input" placeholder="你验证过的邮箱" @keydown.enter="sendLoginCode" />
        </div>
        <div v-if="error" class="err" role="alert">{{ error }}</div>
        <div class="row-btns">
          <button class="submit ghost-btn" @click="phase = 'login'">用密码登录</button>
          <button class="submit" :disabled="busy" @click="sendLoginCode">{{ busy ? "…" : "发送登录码" }}</button>
        </div>
      </template>

      <!-- 验证码登录：输码直接进 -->
      <template v-else-if="phase === 'code-login-verify'">
        <div class="site">验证码登录</div>
        <div class="sub">登录码已飞往 {{ codeLoginEmail }}</div>
        <div class="field">
          <span class="f-label">登录码</span>
          <input v-model="codeLoginCode" class="input" placeholder="6 位数字" maxlength="6" @keydown.enter="doLoginCode" />
        </div>
        <div v-if="notice" class="notice">{{ notice }}</div>
        <div v-if="error" class="err" role="alert">{{ error }}</div>
        <button class="submit" :disabled="busy || codeLoginCode.length !== 6" @click="doLoginCode">{{ busy ? "…" : "进港" }}</button>
        <div class="resend-line">
          <a class="forgot" role="button" tabindex="0" @keydown.enter="($event.currentTarget as HTMLElement).click()" @keydown.space.prevent="($event.currentTarget as HTMLElement).click()" @click="resendCode(codeLoginEmail, 'login')">重新发送</a>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.auth {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(9, 12, 18, 0.28);
  backdrop-filter: blur(10px);
  z-index: 1200;
  padding: 16px;
  overflow-y: auto;
}
.card {
  position: relative;
  width: min(360px, 100%);
  max-height: calc(100dvh - 32px);
  overflow-y: auto;
  padding: 44px 40px 36px;
  background: color-mix(in srgb, var(--bg-panel) 88%, transparent);
  backdrop-filter: blur(18px);
  border: 1px solid rgba(201, 212, 232, 0.12);
  border-radius: 20px;
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.55);
  text-align: center;
  animation: card-in 500ms cubic-bezier(0.22, 1, 0.36, 1);
}
@keyframes card-in {
  from { opacity: 0; transform: translateY(16px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
.logo { font-size: 30px; color: var(--accent); text-shadow: 0 0 18px rgba(201, 212, 232, 0.5); }
.site { margin-top: 12px; font-size: 20px; font-weight: 600; color: var(--text-hi); letter-spacing: 3px; }
.sub { margin-top: 8px; font-size: 12.5px; color: var(--text-lo); letter-spacing: 1px; }
.init-hint {
  margin-top: 22px;
  font-size: 13px;
  color: var(--text-lo);
  line-height: 1.9;
}
.field { margin-top: 16px; text-align: left; }
.f-label { display: block; font-size: 12px; color: var(--text-lo); letter-spacing: 1.5px; margin-bottom: 6px; }
.input {
  width: 100%;
  padding: 10px 13px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-hi);
  font-size: 14px;
  font-family: inherit;
  outline: none;
  transition: border-color 200ms;
}
.input:focus { border-color: var(--accent-dim); }
.remember {
  margin-top: 14px;
  display: flex; align-items: center; gap: 7px;
  font-size: 12.5px; color: var(--text-lo);
  cursor: pointer; user-select: none;
}
.remember input { accent-color: var(--accent); }
.row-line {
  margin-top: 14px;
  display: flex; align-items: center; justify-content: space-between;
}
.row-line .remember { margin-top: 0; }
.row-links { display: flex; gap: 14px; }
.resend-line { margin-top: 12px; text-align: center; }
.forgot { font-size: 12.5px; color: var(--accent); cursor: pointer; }
.forgot:hover { text-decoration: underline; }
.notice { margin-top: 14px; font-size: 12.5px; color: #a8d8b0; }
.row-btns { display: flex; gap: 10px; }
.row-btns .submit { flex: 1; }
.ghost-btn {
  background: transparent;
  color: var(--text-lo);
  border: 1px solid rgba(255, 255, 255, 0.14);
  font-weight: 400;
  letter-spacing: 1px;
}
.ghost-btn:hover { background: rgba(255,255,255,0.06); color: var(--text-hi); box-shadow: none; }
.err { margin-top: 14px; font-size: 12.5px; color: #e8a0bf; }
.submit {
  margin-top: 22px;
  width: 100%;
  padding: 11px;
  border: none;
  border-radius: 11px;
  background: var(--accent);
  color: #141824;
  font-size: 14.5px;
  font-weight: 600;
  letter-spacing: 4px;
  cursor: pointer;
  font-family: inherit;
  transition: all 220ms;
}
.submit:hover { background: #d8e2f5; box-shadow: 0 6px 20px rgba(201, 212, 232, 0.25); }
.submit:disabled { opacity: 0.5; cursor: not-allowed; }
.close-login {position:absolute;right:12px;top:10px;width:28px;height:28px;border:0;border-radius:50%;background:transparent;color:var(--text-lo);font-size:22px;cursor:pointer;}
.close-login:focus-visible {outline:2px solid var(--accent);}
@media(max-width:480px){.card{padding:38px 24px 28px}.row-line{flex-wrap:wrap;gap:12px}.row-links{gap:12px}}
</style>
