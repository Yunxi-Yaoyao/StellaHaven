import { createRouter, createWebHistory } from "vue-router";
import { auth, fetchMe, loggedIn } from "../modules/home/auth";
import {loadNavigation,navigation,resolveLegacyModule} from "../stores/navigation";
import {protectedPage} from "./protectedPage";
import {openLogin,safeLoginTarget} from "../modules/auth/loginPrompt";

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
      component: {render:()=>null},
      meta: { title: "登录", public: true, bare: true },
    },
    { path:"/apps/:id", name:"external-module", props:true, component:{render:()=>null}, meta:{title:"网站模块"} },
    {
      path: "/settings",
      name: "settings",
      component: protectedPage("settings", () => import("../modules/settings/SettingsPage.vue")),
      meta: { title: "设置" },
    },
    {
      path: "/notes",
      name: "notes",
      component: protectedPage("NotesPage", () => import("../modules/notes/NotesPage.vue")),
      meta: { title: "笔记" },
    },
    // Legacy paths only resolve stored migration aliases; never revive a deleted module.
    {path:'/gallery',name:'gallery',component:{render:()=>null},meta:{legacyModule:'gallery'}},
    {path:'/drive',name:'drive',component:{render:()=>null},meta:{legacyModule:'drive'}},
    {
      // 服务器模块：ServersPage 是布局（侧栏 + router-view），右侧内容全部走子路由。
      // 详情页 /status/:id 独立路由——SPA 前端路由切换不刷新页面，左侧外壳不重载。
      path: "/status",
      component: protectedPage("servers", () => import("../modules/servers/ServersPage.vue")),
      meta: { title: "服务器" },
      children: [
        {
          path: "",
          name: "status",
          component: protectedPage("status", () => import("../modules/servers/ServersHome.vue")),
          meta: { title: "服务器" },
        },
        {
          path: ":id(\\d+)",
          name: "status-node",
          component: protectedPage("status-node", () => import("../modules/servers/NodeDetailView.vue")),
          props: (route: { params: { id: string } }) => ({ nodeId: Number(route.params.id) }),
          meta: { title: "节点详情" },
        },
      ],
    },
    { path:'/:pathMatch(.*)*',name:'not-found',component:()=>import('../shell/NotFoundPage.vue'),meta:{title:'页面不存在',public:true} },
  ],
});

// Guests keep the requested URL; private route wrappers cannot import business code.
router.beforeEach(async (to,from) => {
  if(auth.suspended && to.fullPath!==from.fullPath && !to.meta.public){openLogin();return false;}
  // Public page code is independent of the session probe. Start only the selected
  // route import now, but keep rendering and redirects behind the existing guard.
  if (!auth.checked && to.meta.public) {
    for (const record of to.matched) {
      const component = record.components?.default;
      if (typeof component === 'function') {
        void (component as () => Promise<unknown>)().catch(() => {});
      }
    }
  }
  if (!auth.checked) await fetchMe();
  if (to.name==='login'){if(!loggedIn.value)openLogin();return {path:safeLoginTarget(to.query.next),replace:true};}
  if (to.meta.public) {
    return true;
  }
  if (!loggedIn.value) return true;
  if(to.meta.legacyModule){
    if(!navigation.loaded)await loadNavigation();
    const id=resolveLegacyModule(String(to.meta.legacyModule));
    return id?{path:'/apps/'+id,replace:true}:{path:'/settings',query:{section:'navigation'},replace:true};
  }
  return true;
});

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · Stella` : "Stella";
});

export default router;
