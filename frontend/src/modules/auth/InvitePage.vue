<script setup lang="ts">
// 邀请注册页：/invite/<token>。30 分钟内、一链一人。
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { auth } from "../home/auth";
import ParticleCanvas from "../home/ParticleCanvas.vue";

const route = useRoute();
const router = useRouter();
const token = route.params.token as string;

const username = ref("");
const displayName = ref("");
const password = ref("");
const error = ref("");
const busy = ref(false);

async function submit() {
  error.value = "";
  busy.value = true;
  const r = await fetch("/auth/register-invite", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      token,
      username: username.value,
      password: password.value,
      display_name: displayName.value || undefined,
    }),
  });
  busy.value = false;
  if (!r.ok) {
    error.value = (await r.json()).detail ?? "注册失败";
  } else {
    auth.me = await r.json();
    auth.checked = true;
    router.push("/");
  }
}
</script>

<template>
  <div class="auth">
    <div class="stars-bg" />
    <ParticleCanvas mode="stars" />
    <div class="card">
      <div class="logo">✦</div>
      <div class="site">受邀入港</div>
      <div class="sub">管理员给你发了邀请链接——设个账号吧喵~</div>

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
      <div v-if="error" class="err">{{ error }}</div>
      <button class="submit" :disabled="busy" @click="submit">{{ busy ? "…" : "进港" }}</button>
    </div>
  </div>
</template>

<style scoped>
.auth {
  position: fixed; inset: 0;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(168deg, #12151e 0%, #0d1017 50%, #090c12 100%);
}
.stars-bg {
  position: absolute; inset: 0;
  background-image:
    radial-gradient(1.5px 1.5px at 12% 22%, rgba(201,212,232,0.5), transparent),
    radial-gradient(1px 1px at 68% 12%, rgba(201,212,232,0.4), transparent),
    radial-gradient(1.2px 1.2px at 84% 34%, rgba(232,160,191,0.4), transparent),
    radial-gradient(1.6px 1.6px at 52% 82%, rgba(201,212,232,0.3), transparent);
}
.card {
  position: relative; width: 360px;
  padding: 44px 40px 36px;
  background: color-mix(in srgb, var(--bg-panel) 88%, transparent);
  backdrop-filter: blur(18px);
  border: 1px solid rgba(201, 212, 232, 0.12);
  border-radius: 20px;
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.55);
  text-align: center;
}
.logo { font-size: 30px; color: var(--accent); text-shadow: 0 0 18px rgba(201, 212, 232, 0.5); }
.site { margin-top: 12px; font-size: 20px; font-weight: 600; color: var(--text-hi); letter-spacing: 3px; }
.sub { margin-top: 8px; font-size: 12.5px; color: var(--text-lo); letter-spacing: 1px; }
.field { margin-top: 16px; text-align: left; }
.f-label { display: block; font-size: 12px; color: var(--text-lo); letter-spacing: 1.5px; margin-bottom: 6px; }
.input {
  width: 100%; padding: 10px 13px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-hi); font-size: 14px; font-family: inherit; outline: none;
  transition: border-color 200ms;
}
.input:focus { border-color: var(--accent-dim); }
.err { margin-top: 14px; font-size: 12.5px; color: #e8a0bf; }
.submit {
  margin-top: 22px; width: 100%; padding: 11px;
  border: none; border-radius: 11px;
  background: var(--accent); color: #141824;
  font-size: 14.5px; font-weight: 600; letter-spacing: 4px;
  cursor: pointer; font-family: inherit; transition: all 220ms;
}
.submit:hover { background: #d8e2f5; }
.submit:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
