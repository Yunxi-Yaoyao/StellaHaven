<script setup lang="ts">
import {onMounted,onBeforeUnmount,ref,watch} from 'vue';
import {EditorView,keymap,lineNumbers} from '@codemirror/view';
import {EditorState,Compartment} from '@codemirror/state';
import {defaultKeymap,history,historyKeymap} from '@codemirror/commands';
import {syntaxHighlighting,HighlightStyle} from '@codemirror/language';
import {tags} from '@lezer/highlight';
// A dark editor needs dark-theme token colors; CodeMirror's default is light.
const sourceHighlight=HighlightStyle.define([
 {tag:tags.keyword,color:'#c4b5fd'},
 {tag:[tags.name,tags.propertyName],color:'#e8e5ec'},
 {tag:[tags.function(tags.variableName),tags.function(tags.propertyName)],color:'#93c5fd'},
 {tag:[tags.string,tags.special(tags.string),tags.regexp],color:'#f4b8a4'},
 {tag:[tags.number,tags.bool,tags.null,tags.atom],color:'#f2cf8d'},
 {tag:[tags.typeName,tags.className,tags.tagName],color:'#a7dfc1'},
 {tag:[tags.attributeName,tags.labelName,tags.namespace],color:'#b7d5ed'},
 {tag:[tags.comment,tags.meta],color:'#aaa6b5'},
 {tag:[tags.operator,tags.punctuation,tags.bracket],color:'#d3cddd'},
 {tag:tags.heading,color:'#d3c2f7',fontWeight:'bold'},
 {tag:tags.link,color:'#a8d3f0',textDecoration:'underline'},
 {tag:tags.emphasis,fontStyle:'italic'},
 {tag:tags.strong,fontWeight:'bold'},
 {tag:tags.invalid,color:'#ffb4bd',textDecoration:'underline'},
]);
import {languages} from '@codemirror/language-data';
const props=defineProps<{modelValue:string;filename:string;readonly?:boolean}>();const emit=defineEmits<{'update:modelValue':[value:string]}>();const host=ref<HTMLElement|null>(null);let editor:EditorView|undefined,seq=0;const language=new Compartment(),editable=new Compartment();
async function loadLanguage(){const id=++seq;const ext=props.filename.split('.').pop()?.toLowerCase();const found=languages.find(x=>x.extensions.includes(ext||''));const support=found?await found.load():[];if(editor&&id===seq)editor.dispatch({effects:language.reconfigure(support)});}
onMounted(()=>{editor=new EditorView({parent:host.value!,state:EditorState.create({doc:props.modelValue,extensions:[lineNumbers(),history(),keymap.of([...defaultKeymap,...historyKeymap]),syntaxHighlighting(sourceHighlight),language.of([]),editable.of(EditorState.readOnly.of(!!props.readonly)),EditorView.updateListener.of(update=>{if(update.docChanged)emit('update:modelValue',update.state.doc.toString());}),EditorView.theme({'&':{height:'100%',backgroundColor:'var(--bg-base)',color:'var(--text-hi)'},'.cm-scroller':{overflow:'auto',fontFamily:'var(--font-mono)',fontSize:'14px'},'.cm-gutters':{backgroundColor:'var(--bg-panel)',color:'var(--text-faint)',border:'none'},'.cm-content':{caretColor:'var(--text-hi)'},'.cm-cursor':{borderLeftColor:'var(--text-hi)'},'&.cm-focused .cm-selectionBackground, .cm-selectionBackground':{backgroundColor:'var(--selected-bg)'}},{dark:true})]})});void loadLanguage();});
watch(()=>props.filename,()=>{void loadLanguage();});watch(()=>props.readonly,value=>editor?.dispatch({effects:editable.reconfigure(EditorState.readOnly.of(!!value))}));watch(()=>props.modelValue,value=>{if(editor&&editor.state.doc.toString()!==value)editor.dispatch({changes:{from:0,to:editor.state.doc.length,insert:value}});});onBeforeUnmount(()=>{++seq;editor?.destroy();editor=undefined;});
</script>
<template><div ref="host" class="project-code" aria-label="网页源码编辑器" /></template>
<style scoped>.project-code{height:100%;min-height:220px;min-width:0;overflow:hidden}.project-code :deep(.cm-editor){outline:none}</style>
