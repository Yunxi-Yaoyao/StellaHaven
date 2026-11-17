<script setup lang="ts">
import {computed,nextTick,onBeforeUnmount,onMounted,ref,watch} from 'vue';
import {appearance,appearanceError,customAppearance,resolvedPalette,setAppearance,beginAppearanceEdit,setPaletteColor,cancelAppearanceEdit,resetPaletteToken,retryAppearancePersistence} from '../../stores/appearance';
import {type PaletteToken} from '../../stores/appearancePalette';
import {clientPreferenceSync} from './clientPreferenceSync';
import {partContrast,type ThemePart} from './appearanceParts';
import HelpHint from './HelpHint.vue';
import {RouterLink} from 'vue-router';
import ThemeSwitch from './ThemeSwitch.vue';
import AppearanceSample from './AppearanceSample.vue';
const choices=[{key:'A',name:'暮紫 × 桃粉'},{key:'B',name:'鸢尾蓝 × 珊瑚'},{key:'custom',name:'自定义'}] as const;
function loadMode(){try{return localStorage.getItem('stella_appearance_edit_mode')!=='off';}catch{return true;}}
const editing=ref(loadMode()),modeError=ref(''),selected=ref<ThemePart|null>(null),token=ref<PaletteToken>('accent'),colorText=ref(''),inputError=ref('');
const panel=ref<HTMLElement>(),position=ref({top:'100px',left:'8px'});let anchor:HTMLElement|null=null;
const sync=clientPreferenceSync.state;
const color=computed(()=>resolvedPalette.value[token.value]);
const contrast=computed(()=>partContrast(selected.value?.id??'page',resolvedPalette.value));
const contrastWarning=computed(()=>contrast.value<4.5);
function reposition(){if(!anchor || !panel.value)return;const r=anchor.getBoundingClientRect(),p=panel.value.getBoundingClientRect();position.value={left:`${Math.max(8,Math.min(r.right+12,window.innerWidth-p.width-12))}px`,top:`${Math.max(12,Math.min(r.top,window.innerHeight-p.height-12))}px`};}
async function choose(part:ThemePart,element:HTMLElement){cancelAppearanceEdit();selected.value=part;anchor=element;token.value=part.properties[0]!.token;colorText.value=color.value;inputError.value='';beginAppearanceEdit();await nextTick();reposition();panel.value?.querySelector<HTMLInputElement>('[aria-label="颜色值"]')?.focus();}
function property(value:PaletteToken){token.value=value;colorText.value=color.value;inputError.value='';}
function preview(value:string){colorText.value=value;if(!/^#[0-9a-fA-F]{6}$/.test(value)){inputError.value='请输入完整的六位十六进制颜色，如 #C6B5FA';return;}inputError.value='';beginAppearanceEdit();setPaletteColor(token.value,value,true);}
function close(){cancelAppearanceEdit();selected.value=null;inputError.value='';anchor?.focus();}
function mode(value:boolean){close();editing.value=value;try{localStorage.setItem('stella_appearance_edit_mode',value?'on':'off');modeError.value='';}catch{modeError.value='模式仅在当前页面有效，浏览器无法保存此偏好。';}}
function resetOne(){beginAppearanceEdit();resetPaletteToken(token.value,true);colorText.value=color.value;}
function preset(value:typeof choices[number]['key']){close();setAppearance(value);}
function key(event:KeyboardEvent){if(event.key==='Escape' && selected.value){event.preventDefault();close();}}
watch(color,()=>{if(!inputError.value)colorText.value=color.value;});
// Validation and contrast help can grow the fixed editor after its first measure.
// Re-clamp after Vue has rendered that content, keeping bottom actions reachable.
watch([contrastWarning,inputError,token],async()=>{await nextTick();reposition();});
onMounted(()=>{window.addEventListener('keydown',key);window.addEventListener('resize',reposition);window.addEventListener('scroll',reposition,true);});
onBeforeUnmount(()=>{cancelAppearanceEdit();window.removeEventListener('keydown',key);window.removeEventListener('resize',reposition);window.removeEventListener('scroll',reposition,true);});
</script>
<template>
 <section class="appearance-settings" aria-label="全站外观">
  <header><h2>全站外观 <HelpHint label="外观范围">登录后随账号同步，本机保留缓存。有效颜色立即应用并保存；切回 A / B 仍保留一份自定义。仅影响 Stella 自身界面，不改变主页构图、人物、背景或外置网站。</HelpHint></h2></header>
  <div class="appearance-toolbar">
  <div class="appearance-choices" aria-label="配色选择"><button v-for="choice in choices" :key="choice.key" type="button" :aria-pressed="appearance===choice.key" :disabled="choice.key==='custom'&&!customAppearance" @click="preset(choice.key)"><span class="preset-dot" :class="choice.key" aria-hidden="true"/>{{choice.key==='custom'?choice.name:`${choice.key} · ${choice.name}`}}</button></div>
  <div class="mode-control"><span>调色模式</span><ThemeSwitch label="调色模式" :checked="editing" @change="mode"/><HelpHint label="调色模式说明">开启后，点选样板部件调整同类颜色；关闭后可试用组件。切换模式不会改变配色。</HelpHint></div>
  </div>
  <p v-if="appearanceError" class="appearance-error" role="alert">{{appearanceError}} <button class="st-button is-ghost" type="button" @click="retryAppearancePersistence">重试本机保存</button></p>
  <p v-if="modeError" role="alert">{{modeError}}</p>
  <div class="appearance-sync" :class="{'has-error':sync.phase==='error'}" :role="sync.phase==='error'?'alert':'status'">
   <span>{{sync.phase==='synced'?'账号已同步':sync.phase==='saving'||sync.phase==='pending'?'本机已保存 · 正在同步…':sync.phase==='error'?(appearanceError?'同步失败，当前配色仍保留':'同步失败，本机配色已保存'):sync.phase==='conflict'?'其他设备已更改设置，本机配色已保留':'本机保留；登录后随账号同步'}}</span>
   <HelpHint v-if="sync.phase==='error'" label="同步失败详情">{{sync.message}}</HelpHint>
   <button v-if="sync.phase==='error'" class="st-button is-ghost" data-appearance-retry type="button" @click="clientPreferenceSync.retry()">重试</button>
   <details v-if="sync.phase==='conflict'" class="appearance-conflict"><summary>处理</summary><div><p>{{sync.message}} <HelpHint label="配色冲突处理范围">同步当前配色不会替换账号的主页或其他设置；若这些设置也有本机修改，请到备份与恢复页处理。</HelpHint></p><button class="st-button" type="button" @click="clientPreferenceSync.useLocalAppearance()">同步当前配色</button><RouterLink class="st-button is-ghost" to="/settings?section=backups">其他偏好</RouterLink></div></details>
  </div>
  <AppearanceSample :editing="editing" :selected="selected?.id??null" @select="choose"/>
  <aside v-if="selected" ref="panel" class="color-panel" :style="position" role="dialog" aria-modal="false" aria-labelledby="color-panel-title">
   <div class="color-panel-heading"><h3 id="color-panel-title">{{selected.name}}</h3><button type="button" aria-label="关闭调色器" @click="close()">×</button></div><p>{{selected.scope}}</p>
   <div class="color-properties" aria-label="语义属性"><button v-for="prop in selected.properties" :key="prop.token" type="button" :aria-pressed="token===prop.token" @click="property(prop.token)">{{prop.label}}</button></div>
   <div class="color-inputs"><input type="color" aria-label="选取颜色" :value="color" @input="preview(($event.target as HTMLInputElement).value)"/><input aria-label="颜色值" :value="colorText" maxlength="7" spellcheck="false" :aria-invalid="!!inputError" @input="preview(($event.target as HTMLInputElement).value)" @keydown.enter.prevent="close()"/></div>
   <p v-if="inputError" role="alert">{{inputError}}</p>
   <div class="color-panel-actions"><button type="button" @click="resetOne">重置此颜色</button><span class="color-caption">即时保存</span><HelpHint v-if="contrastWarning" label="低对比度提醒">当前文字对比度 {{contrast.toFixed(2)}}:1，低于 4.5:1；可继续调整，不会自动改色。</HelpHint></div>
  </aside>
 </section>
</template>
<style scoped>

.appearance-settings{min-width:0;max-width:1000px}.appearance-settings h2{font-size:20px;font-weight:550;color:var(--text-hi);display:flex;align-items:center;gap:6px}.appearance-choices{display:flex;gap:6px;flex-wrap:wrap}.appearance-choices>button{display:inline-flex;align-items:center;gap:7px;width:auto;flex:none;min-height:34px;padding:5px 9px;border:1px solid var(--control-border);border-radius:7px;background:var(--control-bg);color:var(--text-lo);font:inherit;font-size:13px;cursor:pointer}.appearance-choices>button[aria-pressed=true]{border-color:var(--selected-border);background:var(--selected-bg);color:var(--text-hi)}.appearance-choices>button:disabled{cursor:default;color:var(--text-faint)}.preset-dot{display:inline-block;width:10px;height:10px;flex:none;border-radius:50%;background:var(--accent)}.preset-dot.A{background:linear-gradient(120deg,#C6B5FA 50%,#EFB3C6 50%)}.preset-dot.B{background:linear-gradient(120deg,#B9C1FF 50%,#F1B4AB 50%)}.appearance-toolbar{display:flex;align-items:center;gap:12px 24px;flex-wrap:wrap;margin:12px 0 6px}.appearance-settings>header{margin-bottom:4px}.mode-control{display:flex;align-items:center;gap:10px;font-size:13px}.appearance-sync{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12px;color:var(--text-lo);margin:6px 0 16px;min-height:24px}.appearance-sync.has-error{color:var(--danger)}.appearance-conflict{position:relative}.appearance-conflict summary{cursor:pointer;text-decoration:underline;text-underline-offset:3px;padding:6px}.appearance-conflict>div{position:absolute;right:0;top:100%;box-sizing:border-box;width:280px;max-width:calc(100vw - 40px);z-index:225;padding:12px;background:var(--bg-raised);border:1px solid var(--control-border);border-radius:8px;box-shadow:0 8px 24px #0006}.appearance-conflict p{margin-bottom:8px}.color-panel-actions{align-items:center}.color-caption{font-size:12px;color:#CDC8D6;margin-left:auto}.appearance-error{color:var(--danger);font-size:13px;margin:8px 0}.color-panel{position:fixed;z-index:220;box-sizing:border-box;width:320px;max-width:calc(100vw - 24px);max-height:calc(100dvh - 24px);overflow:auto;padding:16px;border:1px solid #6F697C;border-radius:12px;background:#24222D;color:#F1EDF8;box-shadow:0 12px 42px #0008;font:14px/1.5 var(--font-ui,system-ui)}.color-panel-heading{display:flex;align-items:center;justify-content:space-between;gap:8px}.color-panel h3{font-size:16px;font-weight:550}.color-panel p{font-size:12px;color:#CDC8D6;margin:10px 0}.color-panel button{border:1px solid #655E73;background:#302C3B;color:#F1EDF8;border-radius:6px;padding:5px 8px;min-height:30px;font:inherit;font-size:12px;width:auto;cursor:pointer}.color-panel button:focus-visible,.color-panel input:focus-visible{outline:2px solid #DACDFF;outline-offset:2px}.color-panel-heading>button{background:transparent;border:0;font-size:20px;width:30px;flex:none}.color-properties,.color-panel-actions{display:flex;gap:6px;flex-wrap:wrap}.color-properties button[aria-pressed=true]{border-color:#D0C1FF;background:#49405D}.color-inputs{display:flex;align-items:center;gap:10px;margin:14px 0}.color-inputs input[type=color]{width:48px;height:38px;padding:2px;border:1px solid #756B88;background:#302C3B;border-radius:6px;cursor:pointer}.color-inputs input:not([type]){width:130px;max-width:100%;min-width:0;border:1px solid #756B88;background:#302C3B;color:#F1EDF8;border-radius:6px;padding:7px 9px;font:14px monospace}.color-panel button:disabled{opacity:.65;cursor:default}@media(max-width:640px){.appearance-conflict[open]{flex-basis:100%}.appearance-conflict>div{position:static;width:auto;max-width:100%;margin-top:6px}.appearance-toolbar{gap:10px}.color-panel{left:8px!important;right:8px;top:auto!important;bottom:8px;width:auto;max-width:none;max-height:60dvh;border-radius:14px}.color-panel-actions{gap:9px}.color-panel button{min-height:36px}.appearance-choices>button{min-height:38px}.mode-control{min-height:36px}}
</style>
