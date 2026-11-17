<script setup lang="ts">
import StyleEditor from './StyleEditor.vue';
import NavSelect from './NavSelect.vue';
import NavColor from './NavColor.vue';
import MaterialChoice from './MaterialChoice.vue';
import Icon from '../../shell/Icon.vue';
import {type Preferences,type Asset,type Style} from './types';
const prefs=defineModel<Preferences>({required:true});
const randomId=()=>crypto.randomUUID();
defineProps<{tab:string;assets:Asset[]}>();
const emit=defineEmits<{manageBackground:[]}>();
function changeStyle(s:Style){prefs.value={...prefs.value,layout:s.layout||'icon',textColor:s.textColor??null,hideTitle:s.hideTitle??false,hideDescription:s.hideDescription??false};}
const colors=[['clockColor','时钟颜色'],['searchBackground','搜索背景'],['searchBorder','搜索边框'],['searchText','搜索文字']] as const;
function move(index:number,offset:number){const a=prefs.value.engines;const to=index+offset;if(to<0||to>=a.length)return;const item=a.splice(index,1)[0];if(item)a.splice(to,0,item);}
</script>
<template>
 <template v-if="tab==='display'">
  <StyleEditor :value="prefs" @change="changeStyle"/>
  <div class="nav-fields">
   <label>导航标题<input v-model="prefs.title" maxlength="100"></label>
   <label>标题图片<MaterialChoice label="标题图片" v-model="prefs.titleImage" :assets="assets"/></label>
   <label class="nav-check"><input type="checkbox" v-model="prefs.showTitle">显示导航标题</label>
   <label class="nav-check"><input type="checkbox" v-model="prefs.clock">显示时钟</label>
   <label class="nav-check"><input type="checkbox" v-model="prefs.seconds">时钟显示秒</label>
   <label class="nav-check"><input type="checkbox" v-model="prefs.networkButton">显示设备线路选择</label>
   <label>内容宽度<input type="number" v-model.number="prefs.width" min="1" :max="prefs.widthUnit==='%'?100:2400"></label>
   <label>宽度单位<NavSelect label="宽度单位" v-model="prefs.widthUnit" :options="[{value:'px',label:'px'},{value:'%',label:'%'}]"/></label>
   <label>横向边距（px）<input type="number" v-model.number="prefs.marginX" min="0" max="200"></label>
   <label>顶部边距（%）<input type="number" v-model.number="prefs.marginTop" min="0" max="100"></label>
   <label>底部边距（%）<input type="number" v-model.number="prefs.marginBottom" min="0" max="100"></label>
   <label>卡片间距（px）<input type="number" v-model.number="prefs.gap" min="4" max="40"></label>
   <label>页面留白（px）<input type="number" v-model.number="prefs.padding" min="8" max="80"></label>
   <label>时钟颜色<NavColor label="时钟颜色" v-model="prefs.clockColor"/></label>
  </div>
 </template>
 <template v-if="tab==='background'">
  <div class="nav-fields">
   <label>背景来源<NavSelect label="背景来源" v-model="prefs.background" :options="[{value:'none',label:'无背景'},{value:'home',label:'跟随 Stella 壁纸'},{value:'custom',label:'导航独立背景'}]"/></label>
   <label v-if="prefs.background==='custom'" class="nav-wide">背景素材<MaterialChoice label="背景素材" v-model="prefs.backgroundUrl" :assets="assets" wallpapers/></label>
   <label>模糊（px）<input v-model.number="prefs.blur" type="number" min="0" max="30"></label>
   <label>遮罩<input v-model.number="prefs.mask" type="range" aria-label="遮罩" min="0" max="1" step="0.05"><output>{{prefs.mask}}</output></label>
  </div>
  <button type="button" class="st-button" data-manage-background @click="emit('manageBackground')">管理壁纸与视频</button>
  <p class="nav-hint">复用 Stella 背景图库的上传、视频优化、预览、重命名和删除。选择只改导航草稿，保存后生效；不修改主页壁纸或取景。明亮背景请增加遮罩。</p>
 </template>
 <template v-if="tab==='search'">
  <div class="nav-fields">
   <label class="nav-check"><input v-model="prefs.search" type="checkbox">显示搜索栏（斜杠聚焦）</label>
   <label class="nav-check"><input v-model="prefs.searchIcons" type="checkbox">显示引擎图标</label>
   <label v-for="[key,label] in colors.slice(1)" :key="key">{{label}}<NavColor :label="label" v-model="prefs[key]"/></label>
  </div>
  <label class="nav-check"><input type="checkbox" v-model="prefs.newWindowOpen">外部搜索在新窗口打开</label>
  <label>默认搜索引擎<NavSelect label="默认搜索引擎" v-model="prefs.defaultEngine" :options="[{value:null,label:'第一项'},...prefs.engines.map(e=>({value:e.id,label:e.title}))]"/></label>
  <h3>外部搜索引擎</h3><p class="nav-hint">使用 {query} 代表关键词；Enter 外部搜索，输入时筛选导航。首页切换引擎会保存为账号默认。</p>
  <div v-for="(engine,index) in prefs.engines" :key="engine.id" class="nav-engine-row">
   <label>名称<input v-model="engine.title" maxlength="40"></label><label>搜索地址<input v-model="engine.url" placeholder="https://example.test/?q={query}"></label>
   <label>图标<MaterialChoice :label="'引擎图标 '+engine.title" v-model="engine.icon" :assets="assets"/></label>
   <div class="nav-actions"><button type="button" class="st-button" :disabled="index===0" @click="move(index,-1)" :aria-label="`上移引擎 ${engine.title}`"><Icon name="chevron-down" class="nav-up"/></button><button type="button" class="st-button" :disabled="index===prefs.engines.length-1" @click="move(index,1)" :aria-label="`下移引擎 ${engine.title}`"><Icon name="chevron-down"/></button><button type="button" class="st-button" @click="prefs.engines.splice(index,1);if(prefs.defaultEngine===engine.id)prefs.defaultEngine=null">移除</button></div>
  </div>
  <button class="st-button" type="button" :disabled="prefs.engines.length>=20" @click="prefs.engines.push({id:randomId(),title:'',url:'',icon:''})">新增引擎</button>
 </template>

</template>
