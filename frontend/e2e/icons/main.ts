import { createApp, h, ref } from 'vue';
import '@fontsource-variable/inter';
import '../../src/style.css';
import IconPicker from '../../src/modules/settings/IconPicker.vue';
import Icon from '../../src/shell/Icon.vue';
import { iconCatalog, iconCategories } from '../../src/icons/navigationIcons';
import './fixture.css';

createApp({ setup() {
  const selected = ref(new URLSearchParams(location.search).get('icon') || 'notebook-pen');
  const name = ref('我的知识库');
  const address = ref('https://example.test/knowledge');
  const atlas = new URLSearchParams(location.search).has('atlas');
  return () => h('main', { class: 'fixture' }, [
    h('div', { class:'eyebrow' }, 'STELLA · 组件预览'),
    h('h1', atlas ? '导航图标目录' : '让网站有自己的标记'),
    h('p', { class:'fixture-note' }, '隔离 fixture · 真实组件与样式，无生产接口或保存操作'),
    ...(atlas ? Object.entries(iconCategories).map(([id,label]) => h('section', [h('h2', label), h('div', { class:'atlas' }, iconCatalog.filter(icon => icon.category === id).map(icon => h('div', [h(Icon, {name:icon.key,size:24}), h('span', icon.label), h('small', icon.key)])))])) : [
      h('div', { class:'fields' }, [
        h('label', ['网站名称', h('input', { 'aria-label':'网站名称', value:name.value, onInput:(e:Event) => name.value = (e.target as HTMLInputElement).value })]),
        h('label', ['地址', h('input', { 'aria-label':'地址', value:address.value, onInput:(e:Event) => address.value = (e.target as HTMLInputElement).value })]),
      ]),
      h('h2', '导航图标'),
      h(IconPicker, { modelValue:selected.value, name:name.value, 'onUpdate:modelValue':(value:string) => selected.value=value }),
      h('output', { 'data-selected':selected.value, class:'fixture-note' }, '当前键名：' + selected.value),
    ]),
  ]);
} }).mount('#app');
