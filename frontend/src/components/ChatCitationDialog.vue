<script setup lang="ts">
import { ref, watch, onUnmounted } from 'vue'
import { ElDialog } from 'element-plus'
import { ApiError, errorText } from '../api'
import { chatApi, sourcePosition, type ChatSource } from '../chat'
import ChatMarkdown from './ChatMarkdown.vue'
const props=defineProps<{source:ChatSource|null;requestId:string}>()
const emit=defineEmits<{close:[];revoked:[]}>()
const detail=ref<(ChatSource & {content?:string})|null>(null),error=ref(''),loading=ref(false)
let controller:AbortController|null=null,revision=0
async function load() {
  controller?.abort();const current=++revision;detail.value=null;error.value=''
  if(!props.source)return
  controller=new AbortController();loading.value=true
  try {const result=await chatApi.citation(props.requestId,props.source.chunk_id,controller.signal);if(current===revision)detail.value=result}
  catch(e){if(current===revision&&!(e instanceof DOMException&&e.name==='AbortError')){const revoked=e instanceof ApiError&&[403,404].includes(e.status);error.value=revoked?'此来源已不可读取，可能已撤销发布或访问权限。':errorText(e);if(revoked)emit('revoked')}}
  finally{if(current===revision)loading.value=false}
}
watch(()=>[props.source,props.requestId],load,{immediate:true})
onUnmounted(()=>{revision++;controller?.abort()})
</script>
<template><ElDialog class="chat-citation-dialog" :model-value="!!source" title="知识来源" width="680px" destroy-on-close :close-on-click-modal="false" @close="$emit('close')"><div v-if="loading" class="chat-citation-loading" role="status">正在核对来源访问权限…</div><div v-else-if="error" class="chat-notice" role="alert"><p>{{error}}</p><button class="text-button" @click="load">重新核对</button></div><div v-else-if="detail" class="chat-citation-detail"><h2>{{detail.title}}</h2><p class="chat-source-meta">{{sourcePosition(detail.position)}}</p><ChatMarkdown :content="detail.content || detail.snippet || '此来源没有可显示的正文。'" /></div><div class="form-actions"><button class="button" @click="$emit('close')">关闭来源</button></div></ElDialog></template>
