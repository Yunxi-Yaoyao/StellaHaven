<script setup lang="ts">
import Icon from '../../shell/Icon.vue';
import type {ServiceSite,ServiceSettings} from '../../api/serviceSettings';
import type {DriveBackgroundMode} from '../drive/driveBackground';
defineProps<{site:ServiceSite;appearance:ServiceSettings['appearance'];background:DriveBackgroundMode}>();
</script>
<template><figure class="appearance-preview" aria-label="外观示意预览">
 <div v-if="site==='drive'" class="drive-preview" :data-preview-theme="appearance.theme" :class="{'image-bg':background==='image'}">
  <div v-if="!appearance.simplified" data-preview-brand class="preview-brand"><Icon name="drive" :size="22"/><b>OpenList</b><span>列表 · 网格</span></div>
  <div class="preview-path"><Icon name="home"/> / 我的文件 <span v-if="appearance.simplified"><Icon name="grid"/></span></div>
  <div v-for="name in ['照片','工作文档','OpenList 使用笔记.md']" :key="name" class="preview-file"><Icon :name="name.endsWith('.md')?'note':'folder'"/><span>{{name}}</span><small>—</small></div>
  <div v-if="!appearance.simplified" class="preview-footer">OpenList · 示例页脚</div>
 </div>
 <div v-else class="gallery-preview" :data-preview-logo="appearance.logo">
  <div class="preview-brand"><img v-if="appearance.logo==='stella'" src="/avatar.png" alt="Stella Logo 示意"/>
   <svg v-else width="32" height="32" viewBox="0 0 32 32" role="img" aria-label="原 Logo 示意"><ellipse v-for="(color,index) in ['#e86372','#e8b863','#7cba7a','#60a8d8','#9e7ed8']" :key="color" cx="16" cy="9" rx="5" ry="8" :fill="color" :transform="`rotate(${index*72} 16 16)`"/></svg><b>{{appearance.logo==='stella'?'Stella':'Immich'}}</b><span>照片</span></div>
  <div class="photo-grid"><div v-for="n in 6" :key="n" :class="'photo-'+n"><Icon name="image" :size="26"/></div></div>
 </div>
 <figcaption>示意预览，非原站实时画面；外观保存后生效。</figcaption>
</figure></template>
<style scoped>
.appearance-preview{margin:14px 0 0;max-width:540px;min-width:0}.drive-preview,.gallery-preview{padding:14px;border-radius:10px;border:1px solid #7385a94d;background:#202632;color:#d8e1ef;font-size:12px}.drive-preview[data-preview-theme=original]{background:#f4f6f9;color:#25314b;border-color:#c8d0df}.drive-preview.image-bg{background:linear-gradient(135deg,#365369,#676189 60%,#b68986);color:#fff;text-shadow:0 1px 3px #14171f}.preview-brand,.preview-path,.preview-file{display:flex;gap:10px;align-items:center;padding:9px 2px}.preview-brand span,.preview-path span,.preview-file small{margin-left:auto}.preview-brand img{width:32px;height:32px;object-fit:cover;border-radius:8px}.preview-path{border-bottom:1px solid #8898b642;margin-bottom:5px}.preview-file{padding:12px 2px}.preview-file span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.preview-footer{border-top:1px solid #8898b642;text-align:center;padding-top:10px;opacity:.7}.photo-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:12px}.photo-grid div{height:60px;display:grid;place-items:center;background:linear-gradient(145deg,#667997,#314454);border-radius:4px;color:#c5d4e1}.photo-grid .photo-2,.photo-grid .photo-5{background:linear-gradient(25deg,#777263,#455258)}.photo-grid .photo-3,.photo-grid .photo-4{background:linear-gradient(145deg,#86657c,#4a536a)}figcaption{color:var(--text-lo);font-size:11px;line-height:1.6;margin-top:8px}
</style>
