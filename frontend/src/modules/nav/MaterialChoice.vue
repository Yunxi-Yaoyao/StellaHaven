<script setup lang="ts">
import {ref,watch} from 'vue';
import type {Asset} from './types';
import {backgroundEntries,loadBackgroundEntries,backgroundThumbnail} from '../home/backgroundMedia';
const value=defineModel<string>({required:true});
const props=defineProps<{assets:Asset[];label:string;wallpapers?:boolean}>();
const expanded=ref(false),error=ref('');
watch(expanded,async v=>{if(v&&props.wallpapers)try{await loadBackgroundEntries();}catch{error.value='Stella壁纸库读取失败，可重试或选择导航素材。';}});
</script>
<template><div class="nav-material-choice"><div class="nav-actions"><button type="button" class="st-button" :aria-label="'选择'+label" @click="expanded=!expanded">选择{{label}}</button><button v-if="value" type="button" class="st-button is-ghost" @click="value=''">清除</button><img v-if="value&&!/\.(mp4|webm|ogv)(?:[?#]|$)/i.test(value)" class="nav-choice-thumb" :src="value" alt="当前素材"></div><div v-if="expanded" class="nav-material-grid is-picker"><button v-for="a in assets" :key="a.id" type="button" :aria-label="label+' '+a.name" :aria-pressed="value===a.url" @click="value=a.url;expanded=false"><img :src="a.url" alt=""><span>{{a.name}}</span></button><template v-if="wallpapers"><button v-for="b in backgroundEntries" :key="b.id" type="button" :aria-label="'Stella壁纸 '+b.name" :aria-pressed="value===b.url" @click="value=b.url;expanded=false"><img v-if="backgroundThumbnail(b.url)||b.media?.thumbnail||!b.ext.includes('mp4')" :src="backgroundThumbnail(b.url)||b.media?.thumbnail||b.url" alt=""><span>{{b.name}} · {{b.media?.status||b.ext}}</span></button></template><p v-if="!assets.length&&!backgroundEntries.length">素材库为空，可在素材页上传图片，或使用主站壁纸管理。</p></div><p v-if="error" role="alert">{{error}}</p><details><summary>高级：外部公开素材地址</summary><input :aria-label="label+'地址'" v-model="value" placeholder="https://…"></details></div></template>
