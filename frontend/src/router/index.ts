import { createRouter, createWebHistory } from "vue-router";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      name: "home",
      component: () => import("../modules/home/HomePage.vue"),
      meta: { title: "个人主页" },
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
      path: "/status",
      name: "status",
      component: () => import("../modules/status/StatusPage.vue"),
      meta: { title: "服务器状态" },
    },
  ],
});

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · Stella` : "Stella";
});

export default router;
