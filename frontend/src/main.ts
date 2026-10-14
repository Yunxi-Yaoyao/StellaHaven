import { createApp } from "vue";
import { createPinia } from "pinia";
import "@fontsource-variable/inter"; // 可变字体：任意字重 100-900（正文 475 靠它渲染）
import "./style.css";
import App from "./App.vue";
import router from "./router";
import {installSessionFence} from "./modules/auth/sessionFence";
installSessionFence();
import {installPrivateMedia} from "./modules/auth/privateMedia";
installPrivateMedia();

createApp(App).use(createPinia()).use(router).mount("#app");
