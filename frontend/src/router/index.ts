import { createRouter, createWebHistory } from "vue-router";
import { auth, fetchMe, loggedIn } from "../modules/home/auth";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      name: "home",
      component: () => import("../modules/home/HomePage.vue"),
      meta: { title: "个人主页", public: true }, // 主页公开（不含隐私内容）
    },
    {
      path: "/login",
      name: "login",
      component: () => import("../modules/auth/LoginPage.vue"),
      meta: { title: "登录", public: true, bare: true },
    },
    {
      path: "/invite/:token",
      name: "invite",
      component: () => import("../modules/auth/InvitePage.vue"),
      meta: { title: "受邀入港", public: true, bare: true },
    },
    {
      path: "/settings",
      name: "settings",
      component: () => import("../modules/settings/SettingsPage.vue"),
      meta: { title: "设置" },
    },
    {
      path: "/notes",
      name: "notes",
      component: () => import("../modules/notes/NotesPage.vue"),
      meta: { title: "笔记" },
    },
    {
      path: "/gallery",
      name: "gallery",
      component: () => import("../modules/gallery/GalleryPage.vue"),
      meta: { title: "图库" },
    },
    {
      path: "/drive",
      name: "drive",
      component: () => import("../modules/drive/DrivePage.vue"),
      meta: { title: "网盘" },
    },
    {
      path: "/status",
      name: "status",
      component: () => import("../modules/servers/ServersPage.vue"),
      meta: { title: "服务器" },
    },
  ],
});

// 路由守卫：非公开页面未登录 → /login；已登录访问 /login → 回主页
router.beforeEach(async (to) => {
  if (!auth.checked) await fetchMe();
  if (to.meta.public) {
    if (to.name === "login" && loggedIn.value) return { name: "home" };
    return true;
  }
  if (!loggedIn.value) return { name: "login", query: { next: to.fullPath } };
  return true;
});

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · Stella` : "Stella";
});

export default router;
